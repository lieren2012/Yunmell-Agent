import { beforeEach, describe, expect, it } from "vitest";
import type { KnowledgeBase } from "../../api/modules/knowledgeBases";
import {
  cacheKnowledgeBases,
  readCachedKnowledgeBases,
  splitKnowledgeBases,
} from "./knowledgeLibrary";

function base(
  id: string,
  owner_user_id: number,
  shared = false,
): KnowledgeBase {
  return {
    id,
    owner_user_id,
    name: id,
    description: "",
    default_open: false,
    shared,
    icon_name: "book-open",
    embedding_model: "",
    embedding_dim: 0,
    doc_count: 0,
    max_documents: 100,
    created_at: 0,
    updated_at: 0,
  };
}

describe("knowledge library split", () => {
  beforeEach(() => localStorage.clear());

  it("keeps owned bases personal and other visible bases enterprise", () => {
    const result = splitKnowledgeBases(
      [base("mine", 7), base("shared", 8, true)],
      7,
    );
    expect(result.personal.map((item) => item.id)).toEqual(["mine"]);
    expect(result.enterprise.map((item) => item.id)).toEqual(["shared"]);
  });

  it("scopes offline cache by user", () => {
    cacheKnowledgeBases(7, [base("mine", 7)]);
    expect(readCachedKnowledgeBases(7).map((item) => item.id)).toEqual([
      "mine",
    ]);
    expect(readCachedKnowledgeBases(8)).toEqual([]);
  });
});
