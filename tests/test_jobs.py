import pytest

from ingest.jobs import function_of


@pytest.mark.parametrize("title, function", [
    ("da Vinci Clinical Territory Associate (m/f/d)", "go-to-market"),
    ("Senior Accountant", "g-and-a"),                      # not "account" (sales)
    ("Cost Accounting Manager", "g-and-a"),
    ("Senior Regulatory Affairs Specialist", "regulatory-clinical"),
    ("Sr. Clinical Research Engineer", "regulatory-clinical"),
    ("Clinical Applications Engineer", "field-deployment"),
    ("Sr. Product Manager - Advanced Clinical Applications", "product-design"),
    ("Senior Human Factors Engineer", "product-design"),
    ("Senior Software Engineer - UI Software Architecture & Display Systems", "software"),
    ("Senior FPGA Design Engineer", "hardware"),
    ("Autonomous Vehicle Engineer (Electrical)", "hardware"),
    ("Autonomous Vehicle Planning Engineer Intern", "robotics-controls"),
    ("Senior Supplier Engineer", "manufacturing-ops"),
    ("Warehouse Supervisor", "manufacturing-ops"),
    ("Medical Image Annotation Technician", "ml-ai"),
    ("Research Scientist, Manipulation", "research"),
    ("Senior Radar Engineer, Space", "hardware"),                         # second block: domain words
    ("Senior Software Engineer, Distributed Simulation (C++)", "software"),  # first block beats it
    ("Humanoid Robot Operator, Commercial Site Team (LA)", "robotics-controls"),
    ("Flight Test Operator, Half Moon Bay", "field-deployment"),
    ("Electronics Test Technician", "manufacturing-ops"),
    ("Staff PCB Designer/Layout Engineer, Air Dominance and Strike", "hardware"),
    ("Senior Infrastructure Reliability Engineer", "software"),
    ("Inventory Accounting Manager", "g-and-a"),
    ("Lead Director of Photography", "other"),
])
def test_function_of(title, function):
    assert function_of(title) == function
