from ga4gh.wes import celery
import random
import time


@celery.task(bind=True)
def long_task(self, msg="Test"):
    """Background task that runs a long function with progress reports."""
    verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
    adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
    noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
    message = ''
    total = random.randint(10, 50)
    for i in range(total):
        if not message or random.random() < 0.25:
            message = '{0}: {1} {2} {3}...'.format(
                msg,
                random.choice(verb),
                random.choice(adjective),
                random.choice(noun)
            )
        self.update_state(
            state='PROGRESS',
            meta={'current': i, 'total': total, 'status': message}
        )
        time.sleep(1)
    return {
        'current': 100,
        'total': 100,
        'status': 'Task completed!',
        'result': 42
    }
