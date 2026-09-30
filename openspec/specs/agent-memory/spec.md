## Purpose

Defines what the shopping assistant remembers about a signed-in shopper, how long each kind of memory survives, and what is recalled into the assistant's context on any given turn — so that a returning shopper is recognised and their stated preferences are honoured, while the raw chat transcript decays on a fixed schedule.

## Requirements

### Requirement: Shopper identity gates all memory

The assistant SHALL file memories only against a signed-in shopper. For a signed-out visitor the assistant SHALL neither record nor recall memory, and SHALL answer statelessly.

#### Scenario: Signed-out visitor asks a question
- **WHEN** a visitor who is not signed in sends a message
- **THEN** the assistant answers using only that message
- **AND** no memory is recorded for the turn
- **AND** no memory is recalled for the turn

#### Scenario: Shopper signs in mid-visit
- **WHEN** a visitor signs in and sends their first message
- **THEN** the turn is recorded against their shopper identity
- **AND** memories recorded before they signed in are not attributed to them

### Requirement: Conversational turns are retained for 90 days

The assistant SHALL record every completed turn of a signed-in shopper's conversation as a message memory, and each such memory SHALL expire 90 days after it was written.

#### Scenario: A turn completes
- **WHEN** the assistant has produced an answer for a signed-in shopper
- **THEN** the question and the answer are recorded together as one message memory

#### Scenario: A message memory reaches its retention limit
- **WHEN** more than 90 days have passed since a message memory was written
- **THEN** that memory is no longer recorded and cannot be recalled

#### Scenario: Recording fails
- **WHEN** the memory service cannot record a turn
- **THEN** the shopper still receives their answer
- **AND** the failure is logged
- **AND** the turn is not retried in a way that delays the shopper

### Requirement: Durable shopper facts are extracted and never expire

After answering, the assistant SHALL judge whether the shopper stated a durable fact about themselves — such as a size, a preferred brand, a colour preference, a budget band, or an occasion they are shopping for — and SHALL record each such fact as a fact memory that does not expire. A turn containing no durable fact SHALL produce no fact memory.

#### Scenario: Shopper states a durable preference
- **WHEN** a shopper says their usual size is M
- **THEN** a fact memory recording that size is stored against the shopper
- **AND** that fact memory has no expiry

#### Scenario: Turn contains no durable fact
- **WHEN** a shopper asks only "do you have jeans under 50 EUR?"
- **THEN** the turn is recorded as a message memory
- **AND** no fact memory is written

#### Scenario: Fact judging does not delay the answer
- **WHEN** the assistant judges a turn for durable facts
- **THEN** the judgement happens after the shopper's answer has been produced
- **AND** the time to the shopper's answer is unaffected

#### Scenario: Fact judging fails
- **WHEN** the fact judgement cannot be completed
- **THEN** the message memory for that turn is still recorded
- **AND** the shopper's answer is unaffected

### Requirement: Recent turns are recalled verbatim, older turns compressed

Within the conversation in progress, the assistant SHALL recall the most recent turns in full and SHALL recall older turns in compressed form, so that concrete referents from the immediately preceding exchange — a colour, a price, a named product — remain available to resolve follow-up questions.

#### Scenario: Follow-up references the previous answer
- **WHEN** the assistant has just listed several products and the shopper replies "the black one, do you have it in M?"
- **THEN** the full text of the preceding turn is available to the assistant
- **AND** the assistant can identify which product "the black one" refers to

#### Scenario: Conversation grows beyond the verbatim window
- **WHEN** a conversation has more turns than the verbatim window holds
- **THEN** turns inside the window are recalled in full
- **AND** turns outside it are recalled in compressed form

#### Scenario: Long conversation
- **WHEN** a conversation exceeds the length at which recalling every turn is practical
- **THEN** the assistant recalls only the turns relevant to the shopper's current message
- **AND** the most recent turns remain available in full

### Requirement: Earlier visits inform the current one

On each turn the assistant SHALL also recall relevant memories from the shopper's earlier sessions, in compressed form, in addition to memories from the session in progress. Memories recalled from earlier sessions SHALL NOT be duplicated with those already recalled from the current session.

#### Scenario: Returning shopper is recognised
- **WHEN** a shopper who stated their size in an earlier visit asks about a garment today
- **THEN** the stored size is available to the assistant
- **AND** the assistant can apply it without asking again

#### Scenario: Expired transcript from an earlier visit
- **WHEN** a shopper's earlier session is older than the 90-day message retention
- **THEN** no message memories from that session are recalled
- **AND** facts stored during that session are still recalled

#### Scenario: Overlap between the two recalls
- **WHEN** cross-session recall returns a memory that in-session recall already returned
- **THEN** the assistant receives that memory once, not twice

#### Scenario: Facts compete with transcript for recall capacity
- **WHEN** cross-session recall is performed
- **THEN** stored facts are not crowded out of the result by conversational memories

### Requirement: Recalled memories always render usable text

Every recalled memory SHALL contribute usable text to the assistant's context. Where a memory carries extracted content the assistant SHALL prefer it; where extraction did not complete the assistant SHALL fall back to the underlying exchange. No recalled memory SHALL contribute empty content.

#### Scenario: Memory has extracted content
- **WHEN** a recalled memory carries extracted content
- **THEN** the assistant's context renders that content

#### Scenario: Extraction did not complete for a memory
- **WHEN** a recalled memory has no extracted content because extraction failed
- **THEN** the assistant's context renders the underlying question and answer instead
- **AND** the memory contributes no empty lines

### Requirement: Contradictory facts resolve to the most recent

Where recalled facts contradict one another, the assistant SHALL act on the most recently stated one. To make this possible, each recalled fact SHALL be presented with the time it was stated.

#### Scenario: Shopper's stated preference has changed
- **WHEN** a shopper stated in an earlier visit that their favourite colour is pink, and in a later visit that it is blue
- **THEN** both facts may be recalled
- **AND** each is presented with the time it was stated
- **AND** the assistant acts on blue

#### Scenario: Facts do not contradict
- **WHEN** recalled facts cover different subjects, such as a size and a preferred brand
- **THEN** the assistant may act on all of them

### Requirement: A presenter can date a session into the past

The chat panel SHALL offer a control that sets the date attributed to the session in progress. Memories recorded during that session SHALL carry the chosen date as the time the shopper stated them, while the time of day SHALL follow the real clock so that turns within the session stay in order. A session is dated as a whole: the control SHALL only take effect when set before the first message of that session is sent, and SHALL lock once the conversation has started, so that no session ends up with its turns dated to two different days.

#### Scenario: Presenter dates a session into the past
- **WHEN** a presenter sets the session date to a date several months ago and holds a conversation
- **THEN** memories recorded in that session are attributed to that date
- **AND** turns within the session remain in chronological order relative to one another

#### Scenario: Facts stated in a dated session
- **WHEN** a shopper states a durable fact during a session dated into the past
- **THEN** that fact is attributed to the chosen date
- **AND** a contradicting fact stated in a later, undated session takes precedence over it

#### Scenario: Date changed after the conversation has started
- **WHEN** a presenter tries to change the session date after the first message of that session has been sent
- **THEN** the session keeps the date it started with
- **AND** the panel indicates that a session is dated as a whole

#### Scenario: No date chosen
- **WHEN** no session date is set
- **THEN** memories are attributed to the time they were recorded

#### Scenario: Panel is closed and reopened
- **WHEN** the presenter closes the chat panel and opens it again
- **THEN** the session date control is empty
- **AND** the new conversation is attributed to the present day unless a date is set for it

#### Scenario: Dating a session does not change retention
- **WHEN** a session is dated far enough into the past that its messages would fall outside the 90-day retention
- **THEN** those messages are still recorded and still recallable
- **AND** their retention is counted from when they were actually recorded

### Requirement: A presenter can set this session's message retention

The chat panel SHALL offer a control that sets how long the message memories of the session in progress survive. Because retention is fixed when the session is opened, the control SHALL only take effect when set before the first message of that session is sent, and the panel SHALL make that constraint evident. The chosen retention SHALL NOT affect fact memories, whose own retention takes precedence over the session's.

#### Scenario: Short retention set before the conversation starts
- **WHEN** a presenter sets a retention of one minute and then holds a conversation in which the shopper states a durable fact
- **THEN** the message memories of that conversation stop being recallable once the minute has passed
- **AND** the fact stated during it remains recallable

#### Scenario: Retention changed after the conversation has started
- **WHEN** a presenter changes the retention control after the first message of the session has been sent
- **THEN** the session keeps the retention it was opened with
- **AND** the panel indicates that the change does not apply to this session

#### Scenario: No retention chosen
- **WHEN** no retention is set for a session
- **THEN** that session's message memories are retained for the default 90 days

#### Scenario: Panel is closed and reopened
- **WHEN** the presenter closes the chat panel and opens it again
- **THEN** the retention control is back to its default
- **AND** the next session is opened with the default retention unless one is set for it

#### Scenario: Recall after the transcript has expired
- **WHEN** a shopper returns after the message memories of an earlier session have expired
- **THEN** no message memories from that session are recalled
- **AND** facts stated during that session are still recalled

#### Scenario: Conversation outlives its own retention
- **WHEN** a conversation continues past the retention set for it
- **THEN** its earliest turns stop being recallable while the conversation is still in progress
- **AND** the assistant continues to answer using whatever remains recallable

### Requirement: Memory never blocks the shopper

Memory SHALL be an enhancement rather than a dependency. When the memory service is unavailable or slow, the shopper SHALL still receive an answer.

#### Scenario: Memory service is down at recall time
- **WHEN** memories cannot be recalled for a turn
- **THEN** the assistant answers without them
- **AND** the failure is logged

#### Scenario: One of the recalls fails
- **WHEN** in-session recall succeeds but cross-session recall fails
- **THEN** the assistant answers using the memories it did recall

### Requirement: Product details from memory are leads, not facts

Recalled memories are a record of past conversations, not a record of the catalogue.
The assistant SHALL NOT present a product to the shopper on the strength of a recalled
memory alone: it SHALL look the product up first, and SHALL take that product's price,
availability, sizes and link only from the lookup.

#### Scenario: Recalled conversation names a product
- **WHEN** a recalled memory mentions a product the shopper was shown on an earlier visit
- **THEN** the assistant looks that product up before naming it to the shopper
- **AND** the price, sizes and link it gives come from the lookup, not from the memory

#### Scenario: Remembered product has changed or been withdrawn
- **WHEN** a product named in a recalled memory can no longer be found in the catalogue
- **THEN** the assistant does not present it as available
- **AND** the assistant does not produce a link for it

### Requirement: Recalled memories stay invisible to the shopper

The assistant SHALL use recalled memories to inform its answers without disclosing that a memory store exists. It SHALL NOT announce that it is consulting memories, and SHALL NOT repeat a recalled memory back to the shopper as though it were new information.

#### Scenario: Assistant applies a recalled preference
- **WHEN** the assistant uses a shopper's stored size to filter a recommendation
- **THEN** the answer reflects the size
- **AND** the answer does not state that the size was retrieved from memory

#### Scenario: Nothing relevant was recalled
- **WHEN** recalled memories are not relevant to the shopper's question
- **THEN** the assistant answers without referring to them
