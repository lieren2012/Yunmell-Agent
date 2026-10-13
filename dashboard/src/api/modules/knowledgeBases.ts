import {
  bridgeAgentHeaders,
  request,
  requestBlob,
  requestUpload,
} from "../request";

export interface KnowledgeLimits {
  max_bases_per_owner: number;
  max_docs_per_kb: number;
  max_document_bytes: number;
}

export interface KnowledgeCapability {
  feature_enabled: boolean;
  backend: "onnx" | "remote";
  selected_model: string;
  provider_id: string;
  prerequisites_ok: boolean;
  usable: boolean;
  checks: {
    model_selected: boolean;
    model_downloaded: boolean;
    deps_available: boolean;
    provider_ready: boolean;
  };
  ocr: {
    enabled: boolean;
    backend: "onnx" | "remote";
    model: string;
    provider_id: string;
    prerequisites_ok: boolean;
    usable: boolean;
    checks: {
      deps_available: boolean;
      provider_ready: boolean;
    };
  };
  /**
   * Per-desktop local capability for personal libraries.  This is deliberately
   * separate from the enterprise feature switch: an administrator may leave
   * the shared/enterprise index disabled while users still use local ONNX.
   * Older servers omit this field and the dashboard falls back conservatively.
   */
  personal_local?: {
    backend?: "onnx" | "remote";
    model?: string | null;
    selected_model?: string | null;
    downloaded?: boolean;
    deps_available?: boolean;
    usable?: boolean;
    prerequisites_ok?: boolean;
    download_required?: boolean;
    checks?: {
      model_selected?: boolean;
      model_downloaded?: boolean;
      deps_available?: boolean;
      provider_ready?: boolean;
    };
    ocr?: {
      enabled?: boolean;
      backend?: "onnx" | "remote";
      model?: string | null;
      deps_available?: boolean;
      usable?: boolean;
      prerequisites_ok?: boolean;
      checks?: {
        deps_available?: boolean;
        provider_ready?: boolean;
      };
    };
  };
  limits?: KnowledgeLimits;
}

export interface KnowledgeBase {
  id: string;
  knowledge_base_id?: string;
  pk?: number;
  owner_user_id: number;
  owner_username?: string | null;
  owner_display_name?: string | null;
  name: string;
  description: string;
  default_open: boolean;
  shared: boolean;
  icon_name: string;
  embedding_model: string;
  embedding_dim: number;
  doc_count: number;
  max_documents: number;
  created_at: number;
  updated_at: number;
  scope?: "personal" | "enterprise";
  read_only?: boolean;
}

interface EnterpriseKnowledgeBaseProjection {
  knowledge_base_id: string;
  name: string;
  description: string;
  icon_name: string;
  embedding_model: string;
  embedding_dim: number;
  doc_count: number;
  max_documents: number;
  created_at: number;
  updated_at: number;
  scope: "enterprise";
  read_only: true;
}

interface EnterpriseKnowledgeDocumentProjection {
  id: string;
  document_id: string;
  kb_id: string;
  path: string;
  filename: string;
  is_dir: boolean;
  content_type: string;
  byte_size: number;
  content_hash: string;
  status: KnowledgeDocument["status"];
  error_message: string;
  chunk_count: number;
  created_at: number;
  updated_at: number;
  scope: "enterprise";
  read_only: true;
}

export interface KnowledgeDocument {
  id: string;
  document_id?: string;
  kb_id: string;
  path?: string;
  filename: string;
  is_dir?: boolean;
  content_type: string;
  byte_size: number;
  content_hash: string;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string;
  chunk_count: number;
  created_at: number;
  updated_at: number;
  /** True when the uploaded original still exists on disk. */
  has_original?: boolean;
}

export interface KnowledgeOnnxModel {
  id: string;
  name: string;
  downloaded: boolean;
  recommended?: boolean;
  size_gb?: number | null;
}

export interface KnowledgeEmbeddingOptions {
  onnx: KnowledgeOnnxModel[];
  remote: {
    provider_id: string;
    provider_name: string;
    models: { id: string; name: string }[];
  }[];
}

export interface KnowledgeOcrOptions {
  local: { id: "rapidocr"; name: string };
  remote: {
    provider_id: string;
    provider_name: string;
    models: { id: string; name: string }[];
  }[];
}

export interface KnowledgeOnnxDownloadState {
  status: "idle" | "downloading" | "loading" | "done" | "failed";
  progress: number;
  error?: string | null;
  model_name: string;
  task_id?: string;
}

export const DEFAULT_KNOWLEDGE_LIMITS: KnowledgeLimits = {
  max_bases_per_owner: 20,
  max_docs_per_kb: 100,
  max_document_bytes: 100 * 1024 * 1024,
};

function mapEnterpriseKnowledgeBase(
  row: EnterpriseKnowledgeBaseProjection,
): KnowledgeBase {
  return {
    id: row.knowledge_base_id,
    knowledge_base_id: row.knowledge_base_id,
    owner_user_id: 0,
    owner_username: "企业管理",
    owner_display_name: "企业管理",
    name: row.name,
    description: row.description,
    default_open: false,
    shared: true,
    icon_name: row.icon_name,
    embedding_model: row.embedding_model,
    embedding_dim: row.embedding_dim,
    doc_count: row.doc_count,
    max_documents: row.max_documents,
    created_at: row.created_at,
    updated_at: row.updated_at,
    scope: "enterprise",
    read_only: true,
  };
}

export const knowledgeBasesApi = {
  getCapability: (agentId?: string | null) =>
    request<KnowledgeCapability>("/knowledge-bases/capability", {
      headers: bridgeAgentHeaders(agentId),
    }),

  setFeature: (body: {
    enabled: boolean;
    backend?: "onnx" | "remote";
    model?: string;
    provider_id?: string;
    ocr_enabled?: boolean;
    ocr_backend?: "onnx" | "remote";
    ocr_model?: string;
    ocr_provider_id?: string;
  }) =>
    request<KnowledgeCapability>("/knowledge-bases/feature", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  list: (agentId?: string | null) =>
    request<KnowledgeBase[]>("/knowledge-bases", {
      headers: bridgeAgentHeaders(agentId),
    }),
  listEnterprise: async () => {
    const rows = await request<EnterpriseKnowledgeBaseProjection[]>(
      "/enterprise/knowledge-bases",
    );
    return rows.map(mapEnterpriseKnowledgeBase);
  },
  getEnterprise: async (id: string) =>
    mapEnterpriseKnowledgeBase(
      await request<EnterpriseKnowledgeBaseProjection>(
        `/enterprise/knowledge-bases/${id}`,
      ),
    ),
  listEnterpriseDocuments: async (id: string, prefix?: string) => {
    const suffix = prefix ? `?prefix=${encodeURIComponent(prefix)}` : "";
    const rows = await request<EnterpriseKnowledgeDocumentProjection[]>(
      `/enterprise/knowledge-bases/${id}/documents${suffix}`,
    );
    return rows.map((row) => ({ ...row, has_original: false }));
  },
  previewEnterpriseDocument: (id: string, documentId: string) =>
    request<{ id: string; filename: string; text: string }>(
      `/enterprise/knowledge-bases/${id}/documents/${documentId}/preview`,
    ),
  getEmbeddingOptions: (opts?: { allOnnx?: boolean }) =>
    request<KnowledgeEmbeddingOptions>(
      opts?.allOnnx
        ? "/knowledge-bases/embedding-options?all_onnx=true"
        : "/knowledge-bases/embedding-options",
    ),

  getOcrOptions: () =>
    request<KnowledgeOcrOptions>("/knowledge-bases/ocr-options"),

  downloadOnnx: (model: string) =>
    request<KnowledgeOnnxDownloadState>("/knowledge-bases/onnx-download", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),

  getOnnxDownloadStatus: () =>
    request<KnowledgeOnnxDownloadState>(
      "/knowledge-bases/onnx-download-status",
    ),

  installPersonalOcr: () =>
    request<{
      status: string;
      ready: boolean;
      backend: "onnx";
      model: "rapidocr";
    }>("/knowledge-bases/personal-ocr-install", {
      method: "POST",
    }),

  testOnnx: (model: string) =>
    request<{
      ok: boolean;
      latency_ms?: number | null;
      dim?: number | null;
      error?: string | null;
    }>("/knowledge-bases/onnx-test", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),

  activateOnnx: (model: string) =>
    request<{ enabled: boolean; model: string; ready: boolean }>(
      "/knowledge-bases/onnx-activate",
      {
        method: "POST",
        body: JSON.stringify({ model }),
      },
    ),

  get: (id: string) => request<KnowledgeBase>(`/knowledge-bases/${id}`),

  create: (body: {
    name: string;
    description?: string;
    default_open?: boolean;
    shared?: boolean;
    icon_name?: string;
    max_documents?: number;
  }) =>
    request<KnowledgeBase>("/knowledge-bases", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  update: (
    id: string,
    body: {
      name?: string;
      description?: string;
      default_open?: boolean;
      shared?: boolean;
      icon_name?: string;
      max_documents?: number;
    },
  ) =>
    request<KnowledgeBase>(`/knowledge-bases/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  delete: (id: string) =>
    request<void>(`/knowledge-bases/${id}`, { method: "DELETE" }),

  listDocuments: (id: string, prefix?: string) =>
    request<KnowledgeDocument[]>(
      prefix
        ? `/knowledge-bases/${id}/documents?prefix=${encodeURIComponent(
            prefix,
          )}`
        : `/knowledge-bases/${id}/documents`,
    ),

  createFolder: (id: string, path: string) =>
    request<KnowledgeDocument>(`/knowledge-bases/${id}/folders`, {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  createTextDocument: (
    id: string,
    body: {
      name: string;
      format: "md" | "txt";
      content?: string;
      path?: string;
    },
  ) =>
    request<KnowledgeDocument>(`/knowledge-bases/${id}/documents/text`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getTextDocument: (id: string, documentId: string) =>
    request<{
      id: string;
      filename: string;
      content_type: string;
      text: string;
    }>(`/knowledge-bases/${id}/documents/${documentId}/content`),

  updateTextDocument: (id: string, documentId: string, content: string) =>
    request<KnowledgeDocument>(
      `/knowledge-bases/${id}/documents/${documentId}/content`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  uploadDocument: (
    id: string,
    file: File,
    relativePath?: string,
    onProgress?: (percent: number) => void,
  ) => {
    const body = new FormData();
    body.append("upload", file);
    if (relativePath) body.append("path", relativePath);
    return requestUpload<KnowledgeDocument>(
      `/knowledge-bases/${id}/documents`,
      body,
      { method: "POST" },
      onProgress,
    );
  },

  deleteDocument: (id: string, documentId: string) =>
    request<void>(`/knowledge-bases/${id}/documents/${documentId}`, {
      method: "DELETE",
    }),

  reindexDocument: (id: string, documentId: string) =>
    request<KnowledgeDocument>(
      `/knowledge-bases/${id}/documents/${documentId}/reindex`,
      { method: "POST" },
    ),

  previewDocument: (id: string, documentId: string) =>
    request<{ id: string; filename: string; text: string }>(
      `/knowledge-bases/${id}/documents/${documentId}/preview`,
    ),

  /** Authenticated original-file bytes (download or preview). */
  fetchDocumentFile: (
    id: string,
    documentId: string,
    disposition: "attachment" | "inline" = "attachment",
    onProgress?: (loaded: number, total: number) => void,
    signal?: AbortSignal,
  ) =>
    requestBlob(
      `/knowledge-bases/${id}/documents/${documentId}/file?disposition=${disposition}`,
      { signal },
      onProgress,
    ),

  reindex: (id: string) =>
    request<{ enqueued: number }>(`/knowledge-bases/${id}/reindex`, {
      method: "POST",
    }),

  renameDocument: (id: string, documentId: string, newName: string) =>
    request<KnowledgeDocument>(
      `/knowledge-bases/${id}/documents/${documentId}/rename`,
      {
        method: "POST",
        body: JSON.stringify({ new_name: newName }),
      },
    ),
};
