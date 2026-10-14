import { describe, expect, it } from "vitest";
import { isCurrentUserRow } from "./userIdentity";

describe("isCurrentUserRow", () => {
  const admin = { id: 7, username: "admin" };

  it("uses the stable username when local and remote ids differ", () => {
    expect(isCurrentUserRow({ id: 2, username: "admin" }, admin)).toBe(true);
    expect(isCurrentUserRow({ id: 7, username: "abcde12345" }, admin)).toBe(
      false,
    );
  });

  it("honors an explicit control-plane marker", () => {
    expect(
      isCurrentUserRow(
        { id: 2, username: "someone-else", is_current_user: true },
        admin,
      ),
    ).toBe(true);
    expect(
      isCurrentUserRow(
        { id: 7, username: "admin", is_current_user: false },
        admin,
      ),
    ).toBe(false);
  });

  it("does not identify a row without an authenticated user", () => {
    expect(isCurrentUserRow({ id: 7, username: "admin" }, null)).toBe(false);
  });
});
