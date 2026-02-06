"""
Build the automation root agent: Planner -> LoopAgent(Writer, Validator, Checker).
All config from backend.config (no hardcoded values).
"""
from backend import config
from backend.agents.automation.checker import CheckerAgent
# Removed ExecutorAgent import
from backend.agents.automation.planner import create_planner
from backend.agents.automation.validator import ValidatorAgent
from backend.agents.automation.writer import create_writer
from google.adk.agents import LoopAgent, SequentialAgent


def create_automation_agent() -> SequentialAgent:
    planner = create_planner()
    writer = create_writer()
    validator = ValidatorAgent(name="Validator")
    # ExecutorAgent is removed here
    checker = CheckerAgent(name="Checker")

    loop = LoopAgent(
        name="AutomationLoop",
        # Removed executor from sub_agents list
        sub_agents=[writer, validator, checker],
        max_iterations=config.AUTOMATION_MAX_ITERATIONS,
    )
    return SequentialAgent(
        name="AutomationPipeline",
        sub_agents=[planner, loop],
    )
