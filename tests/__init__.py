"""Tests for ai_shell.

Standard library unittest, no test framework and no new dependencies — the
requirements file is two packages and running the tests shouldn't make it
three.

    python -m unittest discover -s tests -v

Everything here runs offline and in about a second: the model is stubbed and
no page is fetched. The tests that genuinely need the internet and a running
model server live in test_live.py and skip themselves unless asked for:

    AI_SHELL_LIVE_TESTS=1 python -m unittest tests.test_live -v

Almost every case below is a bug that actually happened rather than a shape
somebody imagined going wrong, and each one says which.
"""
