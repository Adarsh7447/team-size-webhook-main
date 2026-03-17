#!/usr/bin/env python3
"""
Quick script to check if async processing is properly configured.
Run this to verify your Celery setup.
"""

import os
import sys


def check_env_vars():
    """Check if required environment variables are set."""
    required = [
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ]

    missing = []
    for var in required:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print("❌ Missing environment variables:")
        for var in missing:
            print(f"   - {var}")
        return False
    else:
        print("✅ All required environment variables are set")
        return True


def check_redis():
    """Check if Redis is accessible."""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
        print(f"✅ Redis is accessible at {redis_url}")
        return True
    except ImportError:
        print("❌ Redis package not installed (pip install redis)")
        return False
    except Exception as e:
        print(f"❌ Cannot connect to Redis: {e}")
        return False


def check_celery():
    """Check if Celery app can be imported."""
    try:
        from src.worker.celery_app import celery_app
        print("✅ Celery app imported successfully")
        return True
    except Exception as e:
        print(f"❌ Cannot import Celery app: {e}")
        return False


def check_tasks():
    """Check if tasks are registered."""
    try:
        from src.worker.celery_app import celery_app
        tasks = list(celery_app.tasks.keys())
        relevant_tasks = [t for t in tasks if "enrich" in t]

        if relevant_tasks:
            print(f"✅ Found {len(relevant_tasks)} enrichment tasks:")
            for task in relevant_tasks:
                print(f"   - {task}")
            return True
        else:
            print("❌ No enrichment tasks found")
            return False
    except Exception as e:
        print(f"❌ Cannot check tasks: {e}")
        return False


def test_task_submission():
    """Test submitting a dummy task."""
    try:
        from src.worker.celery_app import celery_app

        # Try to send a simple debug task
        result = celery_app.send_task(
            "celery.ping",
            args=[],
            kwargs={},
            countdown=1
        )

        print(f"✅ Task submitted successfully (ID: {result.id})")
        print(f"   Task status: {result.status}")

        if result.status == "PENDING":
            print("⚠️  Task is PENDING - this is normal if:")
            print("   1. Worker hasn't picked it up yet (wait a few seconds)")
            print("   2. No worker is running (CHECK THIS!)")
            print("\n   To verify worker is running:")
            print("   - Check Railway logs for celery-worker service")
            print("   - Or run locally: celery -A src.worker.celery_app worker")

        return True

    except Exception as e:
        print(f"❌ Cannot submit task: {e}")
        return False


def main():
    print("=" * 60)
    print("Async Processing Configuration Check")
    print("=" * 60)
    print()

    checks = [
        ("Environment Variables", check_env_vars),
        ("Redis Connection", check_redis),
        ("Celery App", check_celery),
        ("Task Registration", check_tasks),
        ("Task Submission", test_task_submission),
    ]

    results = []
    for name, check_func in checks:
        print(f"\nChecking {name}...")
        print("-" * 60)
        result = check_func()
        results.append(result)
        print()

    print("=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n✅ All checks passed!")
        print("\n⚠️  IMPORTANT: This only checks configuration.")
        print("   To verify async processing works, you MUST have a worker running:")
        print("   - On Railway: Deploy celery-worker service (see RAILWAY_SETUP.md)")
        print("   - Locally: celery -A src.worker.celery_app worker --loglevel=info")
    else:
        print("\n❌ Some checks failed. Fix the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
