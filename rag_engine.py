"""
RAG引擎：文档加载 -> 切分 -> Embedding -> 向量索引 -> 检索
支持 sentence-transformers 和 TF-IDF 双模式，防止模型下载失败
"""

import os
import re
import numpy as np
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ============================================================
# 文档加载与切分
# ============================================================

def load_documents(data_dir: str = DATA_DIR) -> list[dict]:
    """加载知识库文档，按 ===DOCUMENT:=== 分隔"""
    docs = []
    for fname in os.listdir(data_dir):
        if not fname.endswith(".txt"):
            continue
        text = open(os.path.join(data_dir, fname), encoding="utf-8").read()
        # 按文档标记切分
        parts = re.split(r"===DOCUMENT:\s*(.+?)===", text)
        for i in range(1, len(parts), 2):
            title = parts[i].strip()
            content = parts[i + 1].strip()
            # 按段落切分，每段作为一个chunk
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for j, para in enumerate(paragraphs):
                docs.append({
                    "id": f"{title}-{j}",
                    "title": title,
                    "content": para,
                })
    return docs


# ============================================================
# Embedding 引擎（双模式）
# ============================================================

class EmbeddingEngine:
    """向量化引擎，优先使用sentence-transformers，失败回退TF-IDF"""

    def __init__(self):
        self._mode = None
        self._model = None
        self._vectorizer = None
        self._init_model()

    def _init_model(self):
        """尝试加载sentence-transformers，失败则用TF-IDF"""
        try:
            from sentence_transformers import SentenceTransformer
            model_name = "paraphrase-multilingual-MiniLM-L12-v2"
            print(f"[Embedding] 正在加载模型: {model_name} ...")
            self._model = SentenceTransformer(model_name)
            self._mode = "transformer"
            print(f"[Embedding] [OK] 使用 Sentence-Transformer (维度={self._model.get_sentence_embedding_dimension()})")
        except Exception as e:
            print(f"[Embedding] Sentence-Transformer 加载失败: {e}")
            print("[Embedding] -> 回退到 TF-IDF 模式")
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(max_features=512)
            self._mode = "tfidf"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def dim(self) -> int:
        """返回实际向量维度，需在 fit 之后调用"""
        if self._mode == "transformer":
            try:
                return self._model.get_sentence_embedding_dimension()
            except Exception:
                return self._model.get_embedding_dimension()
        elif self._mode == "tfidf" and self._vectorizer is not None:
            try:
                return len(self._vectorizer.get_feature_names_out())
            except Exception:
                pass
        return 384  # 兜底默认值

    def fit(self, texts: list[str]):
        """TF-IDF模式需要先拟合"""
        if self._mode == "tfidf":
            self._vectorizer.fit(texts)

    def encode(self, texts: list[str]) -> np.ndarray:
        """将文本列表转为向量矩阵"""
        if self._mode == "transformer":
            return self._model.encode(texts, normalize_embeddings=True)
        else:
            return self._vectorizer.transform(texts).toarray()


# ============================================================
# 向量索引
# ============================================================

class VectorIndex:
    """向量索引，支持 FAISS 和 NumPy 余弦相似度"""

    def __init__(self, dim: int):
        self._dim = dim
        self._index = None
        self._docs: list[dict] = []
        self._vectors: Optional[np.ndarray] = None
        self._use_faiss = False
        self._init_index()

    def _init_index(self):
        try:
            import faiss
            self._index = faiss.IndexFlatIP(self._dim)  # Inner Product = Cosine (向量已归一化)
            self._use_faiss = True
            print(f"[Index] [OK] 使用 FAISS (IndexFlatIP, dim={self._dim})")
        except Exception as e:
            print(f"[Index] FAISS 加载失败: {e}")
            print("[Index] -> 回退到 NumPy 余弦相似度")

    def add(self, vectors: np.ndarray, docs: list[dict]):
        """批量添加向量和文档"""
        if self._use_faiss:
            self._index.add(vectors.astype(np.float32))
        else:
            self._vectors = vectors.astype(np.float32) if self._vectors is None else \
                np.vstack([self._vectors, vectors.astype(np.float32)])
        self._docs.extend(docs)

    def search(self, query_vec: np.ndarray, top_k: int = 3) -> list[dict]:
        """检索最相似的top_k个文档"""
        query_vec = query_vec.astype(np.float32).reshape(1, -1)

        if self._use_faiss:
            scores, indices = self._index.search(query_vec, top_k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx >= 0 and idx < len(self._docs):
                    doc = dict(self._docs[idx])
                    doc["score"] = float(score)
                    results.append(doc)
            return results
        else:
            # NumPy 余弦相似度
            vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
            doc_vecs = self._vectors / (np.linalg.norm(self._vectors, axis=1, keepdims=True) + 1e-8)
            scores = np.dot(doc_vecs, vec.T).flatten()
            top_indices = np.argsort(scores)[::-1][:top_k]
            results = []
            for idx in top_indices:
                doc = dict(self._docs[idx])
                doc["score"] = float(scores[idx])
                results.append(doc)
            return results

    @property
    def doc_count(self) -> int:
        return len(self._docs)


# ============================================================
# RAG 主类
# ============================================================

class RAGEngine:
    """RAG检索增强生成引擎"""

    def __init__(self):
        self.embedder = EmbeddingEngine()
        self.index: Optional[VectorIndex] = None
        self.docs: list[dict] = []
        self._ready = False

    def build(self):
        """构建知识库索引"""
        print("[RAG] 开始构建知识库...")
        self.docs = load_documents()
        print(f"[RAG] 加载 {len(self.docs)} 个文档片段")

        contents = [d["content"] for d in self.docs]
        self.embedder.fit(contents)

        vectors = self.embedder.encode(contents)
        print(f"[RAG] 向量化完成，shape={vectors.shape}")

        self.index = VectorIndex(self.embedder.dim)
        self.index.add(vectors, self.docs)
        self._ready = True
        print(f"[RAG] ✓ 索引构建完成，共 {self.index.doc_count} 条，embedding模式={self.embedder.mode}")
        return self

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """检索相关文档"""
        if not self._ready:
            return []
        vec = self.embedder.encode([query])
        return self.index.search(vec, top_k)

    def build_prompt(self, query: str, retrieved: list[dict]) -> str:
        """将检索结果拼接成增强Prompt"""
        if not retrieved:
            return query

        context_parts = []
        for i, doc in enumerate(retrieved):
            context_parts.append(f"[参考资料{i+1}] 来源:{doc['title']}\n{doc['content']}")

        context = "\n\n".join(context_parts)
        return f"""请基于以下参考资料回答用户问题。如果资料不足以回答，请明确说明。

{context}

---
用户问题：{query}

请用中文回答，条理清晰。"""
