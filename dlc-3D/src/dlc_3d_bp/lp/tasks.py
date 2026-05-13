"""Celery tasks for lightning-pose training and EKS smoothing."""
from .celery_app import celery


@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, model_dir: str, options: dict) -> dict:
    """Stub — implemented in Phase 5."""
    return {"status": "stub", "model_dir": model_dir, "options": options}


@celery.task(bind=True, name="dlc_3d_lp.eks")
def lp_eks(self, spec: dict) -> dict:
    """Stub — implemented in Phase 4."""
    return {"status": "stub", "spec": spec}
