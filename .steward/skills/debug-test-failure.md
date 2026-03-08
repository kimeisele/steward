# Debug Test Failure
trigger: test, failing test, pytest, assertion, error, debug
---
When a test fails:

1. Run the specific test with verbose output:
   `python -m pytest tests/<file>.py::<TestClass>::<test_method> -xvs --timeout=30`

2. Read the test to understand what it expects

3. Read the source code being tested

4. Common patterns:
   - **AssertionError**: Expected value doesn't match. Check the logic.
   - **ImportError**: Missing dependency or circular import. Check imports.
   - **AttributeError**: Object doesn't have expected field. Check type.
   - **Timeout**: Test hangs. Check for infinite loops or missing mocks.

5. Fix the source code, NOT the test (unless the test is wrong)

6. Run the full suite after fixing: `python -m pytest tests/ -x -q --timeout=30`

Always use `python -m pytest` (not bare `pytest`) to ensure correct Python version.
