"""NCP prompt-validation library. No pytest code here except pytest_plugin.py.

  settings.py       every input: .env / environment, tolerances, connector registry
  prompts.py        the prompt sheet (data/mcp_prompts.xlsx)
  chat/             talk to NCP: client (socket, login, retries), stream (frames -> text), policy
  truth/            read the right answer from each product's own API (read-only)
  grading/          compare an answer with the truth: checks, text helpers, optional judge
  runner.py         one prompt x one connector, end to end -> PromptResult
  results.py        the result record + status rules shared by both reports
  reporting/        Excel workbook and HTML report parts
  pytest_plugin.py  pytest glue: options, pre-flight check, result collection, reports
"""
