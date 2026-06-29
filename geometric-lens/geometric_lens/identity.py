"""Identity metadata for model-coupled Geometric Lens artifacts."""

import json
import os


def canonical_model_identity(value: str) -> str:
    """Return a path-insensitive, extension-insensitive model identity."""
    text = str(value or "").strip().replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    if name.lower().endswith(".gguf"):
        name = name[:-5]
    return name.casefold()


def validate_model_identity(value) -> dict:
    """Validate and normalize a deserialized artifact identity object."""
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    model = value.get("model")
    if not isinstance(model, str) or not canonical_model_identity(model):
        raise ValueError("expected a non-empty model identity")
    dim = value.get("embedding_dim")
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        raise ValueError("expected a positive integer embedding_dim")
    return {"model": model.strip(), "embedding_dim": dim}


def identity_matches(artifact_identity: dict, selected_model: str,
                     embedding_dim: int = 0) -> bool:
    """Return whether an artifact identity belongs to the selected model."""
    identity = validate_model_identity(artifact_identity)
    if canonical_model_identity(identity["model"]) != canonical_model_identity(
            selected_model):
        return False
    return not embedding_dim or identity["embedding_dim"] == int(embedding_dim)


def load_model_identity(models_dir: str) -> dict:
    path = os.path.join(models_dir, "model_identity.json")
    with open(path) as fh:
        return validate_model_identity(json.load(fh))


def save_model_identity(save_dir: str, model: str, embedding_dim: int) -> str:
    identity = validate_model_identity({
        "model": model,
        "embedding_dim": embedding_dim,
    })
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, "model_identity.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(identity, fh, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)
    return path
