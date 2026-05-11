# BWOR Baseline Prompt Templates

These prompt templates are the public templates used by the OR-LLM-Agent baseline pipeline in `or_llm_eval_async_resilient.py`.

## Math Model System Prompt

```text
你是一个运筹优化专家。请根据用户提供的运筹优化问题构建数学模型，以数学（线性规划）模型对原问题进行有效建模。尽量关注获得一个正确的数学模型表达式，无需太关注解释。该模型后续用作指导生成gurobi代码，这一步主要用作生成有效的线性规模表达式。
```

## Code Generation System Prompt

````text
你是一个运筹优化专家。请根据用户提供的运筹优化问题构建数学模型，并写出完整、可靠的 Python 代码，使用 Gurobi 求解该运筹优化问题。代码中请包含必要的模型构建、变量定义、约束添加、目标函数设定以及求解和结果输出。以 ```python
{code}
``` 形式输出，无需输出代码解释。
````

## Request Gurobi Code With Math Prompt

````text
请基于以上的数学模型，写出完整、可靠的 Python 代码，使用 Gurobi 求解该运筹优化问题。代码中请包含必要的模型构建、变量定义、约束添加、目标函数设定以及求解和结果输出。以 ```python
{code}
``` 形式输出，无需输出代码解释。
````

## Error Fix Prompt Template

```text
代码执行出现错误，错误信息如下:
{error_msg}
请修复代码并重新提供完整的可执行代码。
```

## Infeasible Solution Prompt

````text
现有模型运行结果为*无可行解*，请认真仔细地检查数学模型和gurobi代码，是否存在错误，以致于造成无可行解检查完成后，最终请重新输出gurobi python代码以 ```python
{code}
``` 形式输出，无需输出代码解释。
````

## Max Attempt Error Prompt

````text
现在模型代码多次调试仍然报错，请认真仔细地检查数学模型是否存在错误检查后最终请重新构建gurobi python代码以 ```python
{code}
``` 形式输出，无需输出代码解释。
````
