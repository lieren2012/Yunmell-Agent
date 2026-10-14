import type { KnowledgeBase } from "../../api/modules/knowledgeBases";

export type KnowledgeLibraryScope = "personal" | "enterprise";

/** Split the visible rows without changing the server's ownership semantics. */
export function splitKnowledgeBases(
  bases: KnowledgeBase[],
  userId: number | null | undefined,
): { personal: KnowledgeBase[]; enterprise: KnowledgeBase[] } {
  const personal: KnowledgeBase[] = [];
  const enterprise: KnowledgeBase[] = [];
  for (const base of bases) {
    if (userId != null && Number(base.owner_user_id) === Number(userId)) {
      personal.push(base);
    } else {
      enterprise.push(base);
    }
  }
  return { personal, enterprise };
}

export function knowledgeBaseCacheKey(userId: number): string {
  return `octop:knowledge-bases:${userId}`;
}

export function readCachedKnowledgeBases(userId: number): KnowledgeBase[] {
  try {
    const raw = localStorage.getItem(knowledgeBaseCacheKey(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (value): value is KnowledgeBase =>
        Boolean(value) &&
        typeof value === "object" &&
        typeof (value as KnowledgeBase).id === "string" &&
        typeof (value as KnowledgeBase).owner_user_id === "number",
    );
  } catch {
    return [];
  }
}

export function cacheKnowledgeBases(
  userId: number,
  bases: KnowledgeBase[],
): void {
  try {
    localStorage.setItem(knowledgeBaseCacheKey(userId), JSON.stringify(bases));
  } catch {
    // Private browsing or a full storage quota must not block the page.
  }
}
