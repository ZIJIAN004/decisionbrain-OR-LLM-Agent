import sys
import os
# Add parent directory to Python path to find or_llm_eval module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP
from or_llm_eval import or_llm_agent
import io
from contextlib import redirect_stdout
import signal
# Initialize FastMCP server with timeout settings
mcp = FastMCP("or_llm_agent")

@mcp.tool()
def get_operation_research_problem_answer(user_question: str, timeout: int = 600) -> str:
    """
    Use the agent to solve the optimization problem. Agent will generate python gurobi code and run it to get the result.

    Args:
        user_question: The user's question
        timeout: Maximum execution time in seconds (default: 300)

    Returns:
        The result of the optimization problem, including math model, gurobi code and result.
    """
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {timeout} seconds")
    
    # Set up timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    
    try:
        buffer2 = io.StringIO()
        with redirect_stdout(buffer2):
            or_llm_agent(user_question)
        return buffer2.getvalue()
    except TimeoutError as e:
        return f"Error: {str(e)}"
    finally:
        signal.alarm(0)  # Disable alarm

if __name__ == "__main__":
    mcp.run()
