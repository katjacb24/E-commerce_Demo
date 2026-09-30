from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from agentmemory import AgentMemoryError, ChatMessage, MemoryBlock, NotFoundError

from services import memory


def _block(
    *,
    fact: str | None = None,
    user_content: str | None = None,
    assistant_content: str = "",
    summary: str | None = None,
    contexts: list[str] | None = None,
    block_id: str = "b1",
    session_id: str = "session1",
    created_at: str | None = None,
    status: str = "ready",
) -> MemoryBlock:
    """Build a MemoryBlock the way the server returns one.

    Only the fields the recall path reads are set; the rest take their model
    defaults, which is also what a partially-processed block looks like.
    """
    return MemoryBlock(
        block_id=block_id,
        user_id="user1",
        session_id=session_id,
        message=(
            ChatMessage(user_content=user_content, assistant_content=assistant_content)
            if user_content is not None
            else None
        ),
        fact=fact,
        ingested_at="2026-08-31T12:00:00",
        created_at=created_at,
        summary=summary,
        contexts=contexts,
        status=status,
    )


class _FakeSession:
    """Stands in for AsyncSessionResource, recording what it was called with."""

    def __init__(
        self,
        *,
        search_blocks=None,
        list_blocks=None,
        session_id: str = "session1",
        page_size: int | None = None,
    ):
        self.session_id = session_id
        self._search_blocks = search_blocks or []
        self._list_blocks = list_blocks or []
        # Mirrors the server capping a page at whatever limit was asked for.
        self._page_size = page_size
        self.search_calls: list[dict] = []
        self.list_calls: list[dict] = []
        self.add_calls: list[dict] = []

    async def list_memories(self, session_ids=None, limit=20, offset=0, order_by="ingested_at"):
        self.list_calls.append({"limit": limit, "offset": offset})
        size = min(limit, self._page_size) if self._page_size else limit
        page = self._list_blocks[offset : offset + size]
        return type(
            "L",
            (),
            {
                "memory_blocks": page,
                "count": len(page),
                "total": len(self._list_blocks),
                "limit": limit,
                "offset": offset,
            },
        )()

    async def search_memory(self, query=None, filters=None):
        self.search_calls.append({"query": query, "filters": filters})
        return type(
            "R", (), {"memory_blocks": self._search_blocks, "count": len(self._search_blocks)}
        )()

    async def add_memory(self, **kwargs):
        self.add_calls.append(kwargs)
        return type("R", (), {"accepted_count": 1, "rejected_count": 0, "block_ids": ["b"]})()


class _FakeUser:
    def __init__(self, user_id="user1", sessions=None):
        self.user_id = user_id
        self.sessions = sessions or []
        self.created: list[dict] = []
        self.fetched: list[str] = []

    async def create_session(self, session_id, memory_blocks_ttl=None):
        self.created.append(
            {"session_id": session_id, "memory_blocks_ttl": memory_blocks_ttl}
        )
        return _FakeSession(session_id=session_id)

    async def get_session(self, session_id):
        self.fetched.append(session_id)
        return _FakeSession(session_id=session_id)


class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_ninety_days_for_messages_and_never_for_facts(self):
        self.assertEqual(memory.MESSAGE_BLOCK_TTL_SECONDS, 90 * 24 * 60 * 60)
        self.assertEqual(memory.FACT_BLOCK_TTL_SECONDS, 0)

    def test_recall_shape_defaults(self):
        self.assertEqual(memory.VERBATIM_WINDOW_TURNS, 3)
        self.assertEqual(memory.SEARCH_THRESHOLD_TURNS, 10)

    def test_integer_setting_falls_back_when_unset_or_malformed(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(memory._int_env("MEMORY_ABSENT_KEY", 7), 7)
        with patch.dict("os.environ", {"MEMORY_BAD_KEY": "not-a-number"}):
            self.assertEqual(memory._int_env("MEMORY_BAD_KEY", 7), 7)
        with patch.dict("os.environ", {"MEMORY_GOOD_KEY": "42"}):
            self.assertEqual(memory._int_env("MEMORY_GOOD_KEY", 7), 42)


class SessionIdTests(unittest.TestCase):
    def test_first_session_is_session_one(self):
        self.assertEqual(memory._new_session_id("user1", []), "session1")

    def test_next_index_comes_from_the_highest_existing_not_the_count(self):
        # session2 was deleted; the next session must not reuse its number.
        self.assertEqual(
            memory._new_session_id("user1", ["session1", "session3"]), "session4"
        )

    def test_session_id_never_contains_a_path_separator(self):
        # A slash turns into extra URL path segments and the request stops
        # matching the server's route.
        self.assertNotIn("/", memory._new_session_id("user/1", ["session1"]))


class RenderingTests(unittest.TestCase):
    def test_fact_renders_with_the_date_it_was_stated(self):
        rendered = memory.render_block(
            _block(fact="Usual size is M.", created_at="2026-03-14T10:00:00")
        )
        self.assertIn("Usual size is M.", rendered)
        self.assertIn("2026-03-14", rendered)

    def test_fact_falls_back_to_ingested_at_when_created_at_is_absent(self):
        # created_at is documented as nullable; a fact must still carry a time.
        rendered = memory.render_block(_block(fact="Usual size is M."))
        self.assertIn("2026-08-31", rendered)

    def test_fact_is_preferred_over_its_generated_paraphrase(self):
        # The server also summarises a fact, but the paraphrase can drift from
        # what the shopper actually said.
        rendered = memory.render_block(
            _block(fact="Usual size is M.", summary="Usual clothing size is M.")
        )
        self.assertIn("Usual size is M.", rendered)
        self.assertNotIn("clothing", rendered)

    def test_message_renders_question_and_answer(self):
        rendered = memory.render_block(
            _block(user_content="black jeans?", assistant_content="Here are three.")
        )
        self.assertIn("black jeans?", rendered)
        self.assertIn("Here are three.", rendered)

    def test_block_with_neither_fact_nor_message_is_dropped(self):
        blocks = [_block()]
        self.assertEqual(
            memory.render_recalled(blocks, verbatim_turns=len(blocks)), []
        )

    def test_no_rendered_line_is_empty(self):
        blocks = [
            _block(fact="Usual size is M."),
            _block(user_content="hello", assistant_content="hi"),
            _block(),
        ]
        rendered = memory.render_recalled(blocks, verbatim_turns=len(blocks))
        self.assertTrue(all(line.strip() for line in rendered))


class MemoryContextTests(unittest.TestCase):
    def test_no_memories_produces_no_prompt_suffix(self):
        self.assertEqual(memory.memory_context([]), "")

    def test_memories_are_rendered_as_bullets(self):
        rendered = memory.memory_context(["Usual size is M."])
        self.assertIn("- Usual size is M.", rendered)

    def test_prompt_forbids_disclosing_the_memory_store(self):
        rendered = memory.memory_context(["Usual size is M."])
        self.assertIn("Never tell the customer", rendered)

    def test_prompt_instructs_preferring_the_most_recent_of_two_conflicting_facts(self):
        rendered = memory.memory_context(["Favourite colour is blue. (stated 2026-08-01)"])
        self.assertIn("contradict", rendered)
        self.assertIn("most recently", rendered)

    def test_prompt_names_earlier_visits_not_only_this_conversation(self):
        self.assertIn("earlier visits", memory.memory_context(["x"]))

    def test_prompt_forbids_linking_a_product_named_only_in_a_memory(self):
        # Recalled turns are rendered compressed, which drops SKUs, so a product
        # name from memory has no SKU behind it and the agent must look it up.
        rendered = memory.memory_context(["Earlier: User asked about blouses"])
        self.assertIn("never as a result", rendered)
        self.assertIn("Never write a product link whose sku came from a memory", rendered)

    def test_prompt_warns_that_recalled_prices_may_be_stale(self):
        rendered = memory.memory_context(["Earlier: a blouse was 29 EUR"])
        self.assertIn("changed price", rendered)

    def test_rendered_prompt_snapshot(self):
        rendered = memory.memory_context(
            [
                "The shopper's favourite colour is pink. (stated 2026-03-14)",
                "The shopper's favourite colour is blue. (stated 2026-08-30)",
            ]
        )
        self.assertEqual(
            rendered,
            "\n\n    What you already know about this shopper, from this "
            "conversation and from their earlier visits:\n"
            "- The shopper's favourite colour is pink. (stated 2026-03-14)\n"
            "- The shopper's favourite colour is blue. (stated 2026-08-30)\n"
            "    Use these when they help answer the question and ignore them "
            "when they do not. Never tell the customer that you are consulting "
            "stored memories, and never repeat one back as if it were new "
            "information.\n"
            "    Some of these are dated. Where two of them contradict each "
            "other — the same preference stated two different ways — act on the "
            "most recently stated one and disregard the older, because the "
            "customer has changed their mind. Never ask the customer to confirm "
            "which is current.\n"
            "    These memories are a record of past conversations, not catalogue "
            "data. A product named in them may have changed price, changed size "
            "availability, or been withdrawn. So treat any product mentioned here "
            "as a lead to check, never as a result: look it up with a tool before "
            "you name it, take its price, sku and sizes only from what the tool "
            "returns, and leave it out if the tool does not find it. Never write a "
            "product link whose sku came from a memory rather than from a tool "
            "call.\n",
        )


class SessionLifecycleTests(unittest.TestCase):
    def test_existing_session_is_resumed_not_recreated(self):
        user = _FakeUser()
        session = asyncio.run(memory.ensure_session(user, "session7"))
        self.assertEqual(session.session_id, "session7")
        self.assertEqual(user.fetched, ["session7"])
        self.assertEqual(user.created, [])

    def test_new_session_is_created_with_the_message_retention_default(self):
        user = _FakeUser(sessions=["session1"])
        asyncio.run(memory.ensure_session(user, None))
        self.assertEqual(
            user.created,
            [
                {
                    "session_id": "session2",
                    "memory_blocks_ttl": memory.MESSAGE_BLOCK_TTL_SECONDS,
                }
            ],
        )

    def test_user_is_created_on_first_ever_visit(self):
        class _Client:
            def __init__(self):
                self.created = []

            async def get_user(self, user_id):
                raise NotFoundError("nope")

            async def create_user(self, user_id, name):
                self.created.append({"user_id": user_id, "name": name})
                return _FakeUser(user_id=user_id)

        client = _Client()
        asyncio.run(memory.ensure_user(client, "user1", "emily"))
        self.assertEqual(client.created, [{"user_id": "user1", "name": "emily"}])

    def test_username_falls_back_to_the_user_id(self):
        class _Client:
            def __init__(self):
                self.created = []

            async def get_user(self, user_id):
                raise NotFoundError("nope")

            async def create_user(self, user_id, name):
                self.created.append({"user_id": user_id, "name": name})
                return _FakeUser(user_id=user_id)

        client = _Client()
        asyncio.run(memory.ensure_user(client, "user1", None))
        self.assertEqual(client.created, [{"user_id": "user1", "name": "user1"}])


def _turn(n: int, *, summary=None, contexts=None) -> MemoryBlock:
    """One exchange, numbered so assertions can tell them apart."""
    return _block(
        block_id=f"turn{n}",
        user_content=f"question {n}",
        assistant_content=f"answer {n}",
        summary=summary or f"summary of turn {n}",
        contexts=contexts,
    )


async def _recall_in_session(
    session, query: str, *, turn_count: int = 0
) -> list[str]:
    """Fetch and render one session's recall, the way `recall` composes it."""
    blocks = await memory.in_session_blocks(session, query, turn_count=turn_count)
    return memory.render_recalled(
        blocks, verbatim_turns=memory.VERBATIM_WINDOW_TURNS
    )


class InSessionRecallTests(unittest.TestCase):
    """Below the threshold the whole session is listed; above it, search."""

    def _list_session(self, turns: int, turn_count: int):
        # Newest first, the way the server returns a listing.
        blocks = [_turn(n) for n in range(turns, 0, -1)]
        session = _FakeSession(list_blocks=blocks)
        lines = asyncio.run(
            _recall_in_session(session, "which is cheapest?", turn_count=turn_count)
        )
        return session, lines

    def test_short_conversation_is_listed_not_searched(self):
        session, lines = self._list_session(turns=2, turn_count=2)
        self.assertEqual(session.search_calls, [])
        self.assertTrue(session.list_calls)
        self.assertEqual(len(lines), 2)

    def test_every_turn_is_verbatim_inside_the_window(self):
        _, lines = self._list_session(turns=3, turn_count=3)
        self.assertTrue(all(line.startswith("User asked:") for line in lines))

    def test_turns_outside_the_window_are_compressed(self):
        _, lines = self._list_session(turns=9, turn_count=9)
        # Oldest first: the tail is the verbatim window.
        verbatim = [l for l in lines if l.startswith("User asked:")]
        compressed = [l for l in lines if l.startswith("Earlier:")]
        self.assertEqual(len(verbatim), memory.VERBATIM_WINDOW_TURNS)
        self.assertEqual(len(compressed), 9 - memory.VERBATIM_WINDOW_TURNS)
        self.assertTrue(lines[-1].startswith("User asked:"))

    def test_single_turn_conversation_renders_it_verbatim(self):
        _, lines = self._list_session(turns=1, turn_count=1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("User asked:"))

    def test_lines_are_ordered_oldest_first(self):
        # With 4 turns the oldest falls outside the 3-turn window, so it appears
        # first and compressed, and the newest appears last and verbatim.
        _, lines = self._list_session(turns=4, turn_count=4)
        self.assertIn("turn 1", lines[0])
        self.assertTrue(lines[0].startswith("Earlier:"))
        self.assertIn("question 4", lines[-1])

    def test_long_conversation_searches_and_keeps_the_window_verbatim(self):
        recent = [_turn(n) for n in (11, 10, 9)]
        found = [_turn(n) for n in (4, 2)]
        session = _FakeSession(list_blocks=recent, search_blocks=found)
        lines = asyncio.run(
            _recall_in_session(session, "the black one?", turn_count=11)
        )
        self.assertEqual(session.search_calls[0]["query"], "the black one?")
        verbatim = [l for l in lines if l.startswith("User asked:")]
        self.assertEqual(len(verbatim), memory.VERBATIM_WINDOW_TURNS)
        # The searched-up older turns are present, compressed.
        self.assertTrue(any(l.startswith("Earlier:") for l in lines))

    def test_a_block_returned_by_both_search_and_the_window_renders_once(self):
        shared = _turn(11)
        session = _FakeSession(list_blocks=[shared], search_blocks=[shared])
        lines = asyncio.run(_recall_in_session(session, "q", turn_count=11))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("User asked:"))

    def test_facts_do_not_consume_the_verbatim_window(self):
        blocks = [
            _block(block_id="f1", fact="Usual size is M."),
            *[_turn(n) for n in range(4, 0, -1)],
        ]
        session = _FakeSession(list_blocks=blocks)
        lines = asyncio.run(_recall_in_session(session, "q", turn_count=4))
        verbatim = [l for l in lines if l.startswith("User asked:")]
        self.assertEqual(len(verbatim), memory.VERBATIM_WINDOW_TURNS)
        self.assertTrue(any("Usual size is M." in l for l in lines))


class SessionListingPaginationTests(unittest.TestCase):
    def test_a_session_larger_than_one_page_is_fully_fetched(self):
        # The server's default page is 20; a 45-block session must not be
        # silently truncated to the first page.
        blocks = [_turn(n) for n in range(45, 0, -1)]
        session = _FakeSession(list_blocks=blocks, page_size=20)
        fetched = asyncio.run(memory._list_session_blocks(session))
        self.assertEqual(len(fetched), 45)
        self.assertGreater(len(session.list_calls), 1)

    def test_paging_stops_at_the_cap(self):
        blocks = [_turn(n) for n in range(500, 0, -1)]
        session = _FakeSession(list_blocks=blocks, page_size=200)
        fetched = asyncio.run(memory._list_session_blocks(session, cap=200))
        self.assertEqual(len(fetched), 200)

    def test_no_page_is_ever_requested_above_the_server_limit(self):
        blocks = [_turn(n) for n in range(300, 0, -1)]
        session = _FakeSession(list_blocks=blocks, page_size=200)
        asyncio.run(memory._list_session_blocks(session))
        self.assertTrue(all(c["limit"] <= 200 for c in session.list_calls))


class ContextRenderingTests(unittest.TestCase):
    def test_every_context_line_is_kept(self):
        # The real context list from a stored block. The third line is the only
        # one naming actual products, and reads as generic prose — filtering it
        # out destroyed the referent a later "the black one" depends on.
        contexts = [
            "User requested jeans under 70 EUR",
            "The assistant provided a list of jeans available for under 70 EUR",
            "The list includes Men's Light Blue Slim Jeans, Men's Medium-Wash "
            "Slim Jeans, Men's Dark Blue Denim Jeans, and more.",
        ]
        rendered = memory.render_turn(
            _block(user_content="q", assistant_content="a", contexts=contexts),
            verbatim=False,
        )
        for context in contexts:
            self.assertIn(context, rendered)

    def test_product_names_survive_compression(self):
        contexts = ["The list includes Men's Dark Blue Denim Jeans, and more."]
        rendered = memory.render_turn(
            _block(user_content="q", assistant_content="a", contexts=contexts),
            verbatim=False,
        )
        self.assertIn("Dark Blue Denim Jeans", rendered)

    def test_compressed_turn_prefers_contexts_over_summary(self):
        block = _turn(1, summary="a summary", contexts=["User asked about jeans"])
        rendered = memory.render_turn(block, verbatim=False)
        self.assertIn("User asked about jeans", rendered)
        self.assertNotIn("a summary", rendered)

    def test_compressed_turn_falls_back_to_summary(self):
        block = _block(user_content="q", assistant_content="a", summary="a summary")
        self.assertIn("a summary", memory.render_turn(block, verbatim=False))

    def test_compressed_turn_falls_back_to_the_exchange_when_extraction_failed(self):
        # Searchable, ranked, and both extracted fields empty.
        block = _block(
            user_content="do you have pink shirts?",
            assistant_content="Yes, three.",
            status="extraction_failed",
        )
        rendered = memory.render_turn(block, verbatim=False)
        self.assertIn("do you have pink shirts?", rendered)
        self.assertTrue(rendered.strip())

    def test_no_recalled_block_ever_renders_empty(self):
        blocks = [
            _block(user_content="q", assistant_content="a", status="extraction_failed"),
            _turn(2, contexts=["User asked about jeans"]),
            _block(fact="Usual size is M."),
        ]
        lines = memory.render_recalled(blocks, verbatim_turns=1)
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line.strip() for line in lines))


class _FakeLLM:
    """Stands in for the judge's chat model."""

    def __init__(self, reply: str, *, raises: Exception | None = None):
        self._reply = reply
        self._raises = raises
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        return type("R", (), {"content": self._reply})()


class FactValidationTests(unittest.TestCase):
    def test_prose_instead_of_json_stores_nothing(self):
        self.assertEqual(memory.validate_facts("The shopper likes blue"), [])

    def test_non_list_shapes_store_nothing(self):
        for raw in ({"fact": "x"}, 42, None, ("a",)):
            self.assertEqual(memory.validate_facts(raw), [])

    def test_blank_and_oversized_entries_are_dropped(self):
        raw = ["  ", "", "x" * (memory.MAX_FACT_LENGTH + 1), "The shopper wears M."]
        self.assertEqual(memory.validate_facts(raw), ["The shopper wears M."])

    def test_entries_are_trimmed_and_deduplicated(self):
        raw = ["  The shopper wears M.  ", "The shopper wears M."]
        self.assertEqual(memory.validate_facts(raw), ["The shopper wears M."])

    def test_oversized_list_is_capped(self):
        raw = [f"The shopper likes item {i}." for i in range(50)]
        self.assertEqual(len(memory.validate_facts(raw)), memory.MAX_FACTS_PER_TURN)

    def test_non_string_entries_are_skipped(self):
        self.assertEqual(memory.validate_facts([1, {"a": 1}, "The shopper wears M."]),
                         ["The shopper wears M."])


class FactJudgeTests(unittest.TestCase):
    def test_turn_with_a_fact_yields_it(self):
        llm = _FakeLLM('["The shopper\'s usual size is M."]')
        facts = asyncio.run(memory.judge_facts("I wear M", "Noted.", llm=llm))
        self.assertEqual(facts, ["The shopper's usual size is M."])

    def test_turn_without_a_fact_yields_nothing(self):
        llm = _FakeLLM("[]")
        self.assertEqual(
            asyncio.run(memory.judge_facts("jeans under 50?", "Here are six.", llm=llm)),
            [],
        )

    def test_code_fenced_json_is_tolerated(self):
        llm = _FakeLLM('```json\n["The shopper wears M."]\n```')
        self.assertEqual(
            asyncio.run(memory.judge_facts("q", "a", llm=llm)), ["The shopper wears M."]
        )

    def test_malformed_response_yields_nothing_rather_than_raising(self):
        llm = _FakeLLM("Sure! The shopper wears M.")
        self.assertEqual(asyncio.run(memory.judge_facts("q", "a", llm=llm)), [])

    def test_prompt_names_only_the_closed_category_list(self):
        llm = _FakeLLM("[]")
        asyncio.run(memory.judge_facts("q", "a", llm=llm))
        prompt = llm.prompts[0]
        for category in memory.FACT_CATEGORIES:
            self.assertIn(category, prompt)

    def test_prompt_states_that_a_question_is_not_a_fact(self):
        llm = _FakeLLM("[]")
        asyncio.run(memory.judge_facts("q", "a", llm=llm))
        self.assertIn("A question is not a fact", llm.prompts[0])


class RecordTests(unittest.TestCase):
    def test_turn_leaves_processing_to_the_server(self):
        # The block is recallable from both listing and search while it is still
        # `processing` — its message is populated, only the extraction is
        # pending — so waiting the extraction out would only delay the answer.
        session = _FakeSession()
        asyncio.run(memory.record_turn(session, "black jeans?", "Here are three."))
        call = session.add_calls[0]
        self.assertTrue(call["async_processing"])
        self.assertEqual(call["messages"][0].user_content, "black jeans?")

    def test_turn_inherits_the_sessions_retention_rather_than_overriding_it(self):
        # Passing a per-block TTL here would sit above the session's own and
        # silently defeat a session opened with a short retention.
        session = _FakeSession()
        asyncio.run(memory.record_turn(session, "q", "a"))
        self.assertIsNone(session.add_calls[0].get("memory_block_ttl"))

    def test_turn_is_annotated_as_a_turn(self):
        session = _FakeSession()
        asyncio.run(memory.record_turn(session, "q", "a"))
        self.assertEqual(
            session.add_calls[0]["annotations"],
            {memory.ANNOTATION_KEY: memory.TYPE_TURN},
        )

    def test_turn_requests_extraction_so_compressed_recall_has_something_to_show(self):
        session = _FakeSession()
        asyncio.run(memory.record_turn(session, "q", "a"))
        self.assertTrue(session.add_calls[0]["context_required"])

    def test_facts_never_expire_regardless_of_session_retention(self):
        session = _FakeSession()
        asyncio.run(memory.record_facts(session, ["The shopper wears M."]))
        call = session.add_calls[0]
        self.assertEqual(call["memory_block_ttl"], memory.FACT_BLOCK_TTL_SECONDS)
        self.assertEqual(call["memory_block_ttl"], 0)

    def test_facts_are_annotated_as_facts(self):
        session = _FakeSession()
        asyncio.run(memory.record_facts(session, ["The shopper wears M."]))
        self.assertEqual(
            session.add_calls[0]["annotations"],
            {memory.ANNOTATION_KEY: memory.TYPE_FACT},
        )

    def test_facts_skip_extraction_because_they_are_already_atomic(self):
        session = _FakeSession()
        asyncio.run(memory.record_facts(session, ["The shopper wears M."]))
        self.assertFalse(session.add_calls[0]["context_required"])

    def test_no_facts_means_no_write_at_all(self):
        session = _FakeSession()
        asyncio.run(memory.record_facts(session, []))
        self.assertEqual(session.add_calls, [])

    def test_messages_and_facts_are_never_sent_in_one_request(self):
        # The server rejects a request carrying both, so the two must stay
        # separate calls.
        session = _FakeSession()
        asyncio.run(memory.record_turn(session, "q", "a"))
        asyncio.run(memory.record_facts(session, ["The shopper wears M."]))
        self.assertEqual(len(session.add_calls), 2)
        for call in session.add_calls:
            self.assertFalse(call.get("messages") and call.get("facts"))
        self.assertIsNotNone(session.add_calls[0].get("messages"))
        self.assertIsNotNone(session.add_calls[1].get("facts"))


if __name__ == "__main__":
    unittest.main()


class _CrossSessionSession(_FakeSession):
    """Session whose search results depend on the annotation filter asked for."""

    def __init__(self, *, facts=None, turns=None, list_blocks=None, fail=None):
        super().__init__(list_blocks=list_blocks or [])
        self._by_type = {memory.TYPE_FACT: facts or [], memory.TYPE_TURN: turns or []}
        self._fail = fail or set()

    async def search_memory(self, query=None, filters=None):
        self.search_calls.append({"query": query, "filters": filters})
        annotations = (filters or {}).get("annotations") or {}
        block_type = annotations.get(memory.ANNOTATION_KEY)
        if block_type in self._fail:
            raise AgentMemoryError(f"{block_type} search is down")
        blocks = self._by_type.get(block_type, [])
        return type("R", (), {"memory_blocks": blocks, "count": len(blocks)})()


class CrossSessionRecallTests(unittest.TestCase):
    def test_facts_and_turns_are_searched_as_separate_filtered_queries(self):
        session = _CrossSessionSession()
        asyncio.run(memory.recall_across_sessions(session, "what fits me?"))
        filters = [c["filters"] for c in session.search_calls]
        self.assertEqual(len(filters), 2)
        for f in filters:
            self.assertEqual(f["session_ids"], "all")
        by_type = {f["annotations"][memory.ANNOTATION_KEY]: f for f in filters}
        self.assertEqual(
            by_type[memory.TYPE_FACT]["relevant_k"], memory.CROSS_SESSION_FACT_K
        )
        self.assertEqual(
            by_type[memory.TYPE_TURN]["relevant_k"], memory.CROSS_SESSION_TURN_K
        )

    def test_the_two_budgets_are_independent(self):
        # A turn search returning its full allowance must not displace any fact.
        facts = [_block(block_id=f"f{i}", fact=f"Fact {i}.") for i in range(3)]
        turns = [_turn(i) for i in range(memory.CROSS_SESSION_TURN_K)]
        session = _CrossSessionSession(facts=facts, turns=turns)
        got_facts, got_turns = asyncio.run(
            memory.recall_across_sessions(session, "q")
        )
        self.assertEqual(len(got_facts), 3)
        self.assertEqual(len(got_turns), memory.CROSS_SESSION_TURN_K)

    def test_losing_the_turn_search_does_not_lose_the_fact_search(self):
        facts = [_block(block_id="f1", fact="Usual size is M.")]
        session = _CrossSessionSession(facts=facts, fail={memory.TYPE_TURN})
        got_facts, got_turns = asyncio.run(memory.recall_across_sessions(session, "q"))
        self.assertEqual(len(got_facts), 1)
        self.assertEqual(got_turns, [])

    def test_losing_the_fact_search_does_not_lose_the_turn_search(self):
        session = _CrossSessionSession(turns=[_turn(1)], fail={memory.TYPE_FACT})
        got_facts, got_turns = asyncio.run(memory.recall_across_sessions(session, "q"))
        self.assertEqual(got_facts, [])
        self.assertEqual(len(got_turns), 1)


class CombinedRecallTests(unittest.TestCase):
    """recall() joins the conversation in progress to the shopper's history."""

    def test_earlier_visits_come_first_and_the_live_conversation_last(self):
        session = _CrossSessionSession(
            facts=[_block(block_id="f1", fact="Usual size is M.")],
            list_blocks=[_turn(1)],
        )
        lines = asyncio.run(memory.recall(session, "what fits?", turn_count=1))
        self.assertIn("Usual size is M.", lines[0])
        self.assertTrue(lines[-1].startswith("User asked:"))

    def test_cross_session_turns_are_always_compressed(self):
        session = _CrossSessionSession(
            turns=[_turn(9, contexts=["User asked about jeans"])],
            list_blocks=[],
        )
        lines = asyncio.run(memory.recall(session, "q", turn_count=1))
        self.assertTrue(all(not l.startswith("User asked:") for l in lines))
        self.assertTrue(any(l.startswith("Earlier:") for l in lines))

    def test_a_block_recalled_both_ways_renders_once(self):
        # Searching "all" sessions returns the live session's blocks too.
        shared = _turn(1)
        session = _CrossSessionSession(turns=[shared], list_blocks=[shared])
        lines = asyncio.run(memory.recall(session, "q", turn_count=1))
        self.assertEqual(len(lines), 1)
        # The in-session copy wins, so it stays verbatim.
        self.assertTrue(lines[0].startswith("User asked:"))

    def test_in_session_failure_still_yields_the_shoppers_facts(self):
        class _Broken(_CrossSessionSession):
            async def list_memories(self, **kwargs):
                raise AgentMemoryError("listing is down")

        session = _Broken(facts=[_block(block_id="f1", fact="Usual size is M.")])
        lines = asyncio.run(memory.recall(session, "q", turn_count=1))
        self.assertEqual(len(lines), 1)
        self.assertIn("Usual size is M.", lines[0])

    def test_total_failure_yields_no_memories_rather_than_raising(self):
        class _AllBroken(_CrossSessionSession):
            async def list_memories(self, **kwargs):
                raise AgentMemoryError("down")

            async def search_memory(self, query=None, filters=None):
                raise AgentMemoryError("down")

        lines = asyncio.run(memory.recall(_AllBroken(), "q", turn_count=1))
        self.assertEqual(lines, [])
