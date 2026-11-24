"""Shell completion scripts generated from the command catalog (static tables, no runtime callback)."""

from __future__ import annotations

from bento.interfaces.cli.catalog import GLOBAL_ARGS, all_commands

SHELLS = ("bash", "zsh", "fish", "powershell")


def completion_table() -> dict[str, list[str]]:
    """`"vault recovery"` → subcommands and flags available after those words; `""` is the top level."""
    table: dict[str, list[str]] = {}
    global_flags = [flag for item in GLOBAL_ARGS for flag in item.flags if flag.startswith("--")]
    commands = [command for command in all_commands() if not command.hidden]
    by_path = {command.path: command for command in commands}
    for command in commands:
        parent = " ".join(command.path[:-1])
        table.setdefault(parent, []).append(command.path[-1])
    for command in commands:
        key = " ".join(command.path)
        words = table.setdefault(key, [])
        args = list(command.args)
        if command.default_child and (*command.path, command.default_child) in by_path:
            args += by_path[(*command.path, command.default_child)].args
        for item in args:
            words.extend(flag for flag in item.flags if flag.startswith("-"))
            for choice in item.options.get("choices", ()) if item.positional else ():
                words.append(str(choice))
        words.extend(global_flags)
    table.setdefault("", []).extend(global_flags + ["--version", "--help"])
    return {key: sorted(dict.fromkeys(words)) for key, words in table.items()}


def completion_script(shell: str) -> str:
    table = completion_table()
    if shell == "bash":
        return _bash(table)
    if shell == "zsh":
        return "#compdef bento\nautoload -U +X bashcompinit && bashcompinit\n" + _bash(table)
    if shell == "fish":
        return _fish(table)
    if shell == "powershell":
        return _powershell(table)
    raise ValueError(shell)


def _bash(table: dict[str, list[str]]) -> str:
    entries = "\n".join(f'  ["{("bento " + key).strip()}"]="{" ".join(words)}"' for key, words in sorted(table.items()))
    return f"""# bento completion (bash). Install: bento completion bash > ~/.local/share/bash-completion/completions/bento
declare -gA _BENTO_WORDS=(
{entries}
)
_bento() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}" path="bento" word candidate
  local i
  for ((i = 1; i < COMP_CWORD; i++)); do
    word="${{COMP_WORDS[i]}}"
    [[ "$word" == -* ]] && continue
    candidate="$path $word"
    [[ -n "${{_BENTO_WORDS[$candidate]+x}}" ]] && path="$candidate"
  done
  local words="${{_BENTO_WORDS[$path]}}" subs=""
  if [[ "$cur" == -* ]]; then
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
    return
  fi
  for word in $words; do [[ "$word" != -* ]] && subs+="$word "; done
  COMPREPLY=($(compgen -W "$subs" -- "$cur"))
}}
complete -o default -F _bento bento
"""


def _fish(table: dict[str, list[str]]) -> str:
    lines = ["# bento completion (fish). Install: bento completion fish > ~/.config/fish/completions/bento.fish"]
    global_flags = [flag for item in GLOBAL_ARGS for flag in item.flags if flag.startswith("--")]
    lines += [f"complete -c bento -l {flag[2:]}" for flag in global_flags]
    for key, words in sorted(table.items()):
        subcommands = [word for word in words if not word.startswith("-")]
        flags = [word for word in words if word.startswith("--") and word not in global_flags]
        if key == "":
            condition = "__fish_use_subcommand"
        else:
            parts = key.split(" ")
            condition = " && ".join(f"__fish_seen_subcommand_from {part}" for part in parts)
        if subcommands:
            lines.append(f"complete -c bento -f -n '{condition}' -a '{' '.join(subcommands)}'")
        for flag in flags:
            lines.append(f"complete -c bento -n '{condition}' -l {flag[2:]}")
    return "\n".join(lines) + "\n"


def _powershell(table: dict[str, list[str]]) -> str:
    entries = "\n".join(f"  '{key}' = @({', '.join(repr(word) for word in words)})" for key, words in sorted(table.items()))
    return f"""# bento completion (PowerShell). Install: bento completion powershell | Out-String | Invoke-Expression
$BentoWords = @{{
{entries}
}}
Register-ArgumentCompleter -Native -CommandName bento -ScriptBlock {{
  param($wordToComplete, $commandAst, $cursorPosition)
  $path = ''
  foreach ($element in $commandAst.CommandElements | Select-Object -Skip 1) {{
    $word = $element.ToString()
    if ($word -eq $wordToComplete) {{ break }}
    if ($word.StartsWith('-')) {{ continue }}
    $candidate = if ($path) {{ "$path $word" }} else {{ $word }}
    if ($BentoWords.ContainsKey($candidate)) {{ $path = $candidate }}
  }}
  $BentoWords[$path] | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
  }}
}}
"""
