from __future__ import annotations

from fyuneru.dramatiq_toolkit import enqueue_many, new_message


class FakeBroker:
    def __init__(self, fail_indexes: set[int] | None = None):
        self.fail_indexes = fail_indexes or set()
        self.enqueued = 0

    def enqueue(self, message):
        current = self.enqueued
        self.enqueued += 1
        if current in self.fail_indexes:
            raise RuntimeError("enqueue failed")
        return message


def test_enqueue_many_all_success() -> None:
    broker = FakeBroker()
    messages = [
        new_message(actor_name="task", queue_name="default", args=(1,)),
        new_message(actor_name="task", queue_name="default", args=(2,)),
    ]

    result = enqueue_many(broker, messages)
    assert result.success_count == 2
    assert result.failure_count == 0
    assert result.failures == []


def test_enqueue_many_partial_failure() -> None:
    broker = FakeBroker(fail_indexes={1})
    messages = [
        new_message(actor_name="task", queue_name="default", args=(1,)),
        new_message(actor_name="task", queue_name="default", args=(2,)),
        new_message(actor_name="task", queue_name="default", args=(3,)),
    ]

    result = enqueue_many(broker, messages)
    assert result.success_count == 2
    assert result.failure_count == 1
    assert len(result.failures) == 1
    assert result.failures[0][0] == 1


if __name__ == "__main__":
    test_enqueue_many_all_success()
    test_enqueue_many_partial_failure()
    print("dramatiq_toolkit 测试通过")
