# Pytest configuration for backend tests.
# Registers custom markers so "pytest -m 'not integration'" works without warnings.
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration (requires DB with company, branch, user, item and stock)",
    )
