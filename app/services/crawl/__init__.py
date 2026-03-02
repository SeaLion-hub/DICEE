"""Crawl package namespace with lazy entrypoint exports."""

__all__ = [
    "crawl_college_sync",
    "handle_crawl_failure_composite",
    "run_crawl_job_sync",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from app.services.crawl.entrypoints import (
        crawl_college_sync,
        handle_crawl_failure_composite,
        run_crawl_job_sync,
    )

    exports = {
        "crawl_college_sync": crawl_college_sync,
        "handle_crawl_failure_composite": handle_crawl_failure_composite,
        "run_crawl_job_sync": run_crawl_job_sync,
    }
    value = exports[name]
    globals()[name] = value
    return value
