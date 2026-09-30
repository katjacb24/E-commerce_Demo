// Demo-only credentials. The login is faked (client side, plain-text, no
// session) purely so the Personal assistant can be shown answering as a known
// shopper and pulling that shopper's Couchbase agent memory.
const DEMO_USERS = [
  { user_id: "user1Emily", username: "emily", password: "123", displayName: "Emily" },
  { user_id: "user2John", username: "john", password: "123", displayName: "John" },
] as const;

export type DemoUser = {
  user_id: string;
  username: string;
  displayName: string;
};

export function authenticate(username: string, password: string): DemoUser | null {
  const normalizedUsername = username.trim().toLowerCase();
  const match = DEMO_USERS.find(
    (user) => user.username === normalizedUsername && user.password === password
  );

  if (!match) {
    return null;
  }

  return { user_id: match.user_id, username: match.username, displayName: match.displayName };
}
