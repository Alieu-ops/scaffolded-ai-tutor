"""
Module 3: knowledge base (retrieval, often called RAG).

1. Notes in data/knowledge/ are split into passages (one per "## " heading).
2. Each passage is turned into an EMBEDDING, a list of 384 numbers that
   captures its meaning, by a small model (all-MiniLM-L6-v2). Passages
   with similar meaning get similar numbers.
3. ChromaDB stores the passages and embeddings on disk (folder chroma/).
4. When the student asks something, the question is embedded the same
   way and the closest passages FOR THE CURRENT SKILL are returned. The
   tutor pastes them into its instructions.

File names decide the skill: trigonometry.md -> skill "trigonometry".
Any other file (e.g. syllabus_overview.md) is "general" and used for all skills.

Build (or rebuild after editing notes):   python -m tutor.retrieval build
Try a search:   python -m tutor.retrieval "how do I find a back bearing" trigonometry

The embedding model is downloaded once (~90 MB) and then works offline.
"""

import re
import sys

from tutor.skills import PROJECT_ROOT, load_config, load_skills

COLLECTION = "knowledge"


def split_into_passages(text):
    """Split a notes file at each '## ' heading. Returns (heading, body) pairs."""
    parts = re.split(r"^## +", text, flags=re.MULTILINE)
    passages = []
    for part in parts[1:]:                     # parts[0] is the file title
        heading, _, body = part.partition("\n")
        if body.strip():
            passages.append((heading.strip(), body.strip()))
    if not passages and text.strip():          # file without headings
        passages.append(("", text.strip()))
    return passages


def _open(config):
    """Load the embedding model and the ChromaDB collection."""
    import chromadb
    from sentence_transformers import SentenceTransformer

    name = config["retrieval"]["embedding_model"]
    try:
        # Use the copy already downloaded, so this works without internet.
        model = SentenceTransformer(name, local_files_only=True)
    except Exception:
        model = SentenceTransformer(name)   # first time: download it
    client = chromadb.PersistentClient(
        path=str(PROJECT_ROOT / config["retrieval"]["db_dir"]),
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )
    return model, client


def build_index(config):
    """Read all notes, embed every passage, and save them in ChromaDB."""
    model, client = _open(config)
    skills = load_skills(config)
    knowledge_dir = PROJECT_ROOT / config["data"]["knowledge_dir"]

    # Start fresh so deleted or edited notes do not linger.
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    collection = client.create_collection(COLLECTION)

    ids, texts, metadatas = [], [], []
    for path in sorted(knowledge_dir.glob("*")):
        if path.suffix.lower() not in (".md", ".txt"):
            continue
        skill = path.stem if path.stem in skills else "general"
        for n, (heading, body) in enumerate(split_into_passages(path.read_text(encoding="utf-8"))):
            ids.append(f"{path.stem}-{n}")
            texts.append(f"{heading}: {body}" if heading else body)
            metadatas.append({"skill": skill, "source": path.name, "heading": heading})

    if not texts:
        sys.exit(f"No .md or .txt notes found in {knowledge_dir}")

    embeddings = model.encode(texts).tolist()
    collection.add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)
    print(f"Indexed {len(texts)} passages from {knowledge_dir}")


class Retriever:
    """Searches the notes. Created once per session."""

    def __init__(self, config):
        self.model, client = _open(config)
        self.collection = client.get_collection(COLLECTION)  # error if not built

    def search(self, query, skill, k=3):
        """The k passages closest in meaning to `query`, for this skill."""
        embedding = self.model.encode([query]).tolist()
        result = self.collection.query(
            query_embeddings=embedding,
            n_results=k,
            where={"skill": {"$in": [skill, "general"]}},
        )
        return result["documents"][0]


if __name__ == "__main__":
    cfg = load_config()
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build_index(cfg)
    elif len(sys.argv) == 3:
        for passage in Retriever(cfg).search(sys.argv[1], skill=sys.argv[2]):
            print("-", passage[:150], "...\n")
    else:
        print(__doc__)
