import type { OctopUser } from "../../../api/modules/auth";

export interface UserIdentityRow {
  id: number;
  username: string;
  /** Set by a control plane when this row is the authenticated actor. */
  is_current_user?: boolean;
}

/**
 * Match a management-list row to the authenticated actor.
 *
 * In the desktop client, /auth/me is served by the local runtime and carries
 * the local identity projection id, while /users is forwarded from the
 * control plane and carries the remote user id. The username is the stable
 * identity across that boundary; an explicit server marker wins when one is
 * available.
 */
export function isCurrentUserRow(
  row: UserIdentityRow,
  currentUser: Pick<OctopUser, "id" | "username"> | null,
): boolean {
  if (!currentUser) return false;
  if (typeof row.is_current_user === "boolean") return row.is_current_user;
  const rowUsername = row.username.trim().toLowerCase();
  const currentUsername = currentUser.username.trim().toLowerCase();
  if (rowUsername && currentUsername) return rowUsername === currentUsername;
  return row.id === currentUser.id;
}
