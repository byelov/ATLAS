"""Geometric Lens — C(x) cost field + G(x) XGBoost ensemble for code quality estimation."""

import os


def default_models_dir() -> str:
    """Directory the lens loads its artifacts from and retrains into.

    Compose bind-mounts ATLAS_LENS_MODELS over the in-package default. The
    native macOS deployment has no mount, so its wrapper passes the same
    directory as ATLAS_LENS_MODELS_DIR.
    """
    return os.environ.get("ATLAS_LENS_MODELS_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "models")
