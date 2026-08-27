from celery import Celery

from most_sprite.config import get_settings

settings = get_settings()
celery_app = Celery("most-sprite", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="formal-processing",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
celery_app.autodiscover_tasks(["most_sprite.worker"])
