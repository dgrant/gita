import os
import yaml
import asyncio
import platform
from functools import lru_cache
from typing import List, Dict, Coroutine, Union

from . import info


def get_path_fname() -> str:
    """
    Return the file name that stores the repo locations.
    """
    root = os.environ.get('XDG_CONFIG_HOME') or os.path.join(
        os.path.expanduser('~'), '.config')
    return os.path.join(root, 'gita', 'repo_path')


@lru_cache()
def get_repos() -> Dict[str, str]:
    """
    Return a `dict` of repo name to repo absolute path
    """
    path_file = get_path_fname()
    repos = {}
    # Each line is a repo path and repo name separated by ,
    if os.path.isfile(path_file) and os.stat(path_file).st_size > 0:
        with open(path_file) as f:
            for line in f:
                line = line.rstrip()
                if not line:  # blank line
                    continue
                path, name = line.split(',')
                if not is_git(path):
                    continue
                if name not in repos:
                    repos[name] = path
                else:  # repo name collision for different paths: include parent path name
                    par_name = os.path.basename(os.path.dirname(path))
                    repos[os.path.join(par_name, name)] = path
    return repos


def get_choices() -> List[Union[str, None]]:
    """
    Return all repo names and an additional empty list. This is a workaround of
    argparse's problem with coexisting nargs='*' and choices.
    See https://utcc.utoronto.ca/~cks/space/blog/python/ArgparseNargsChoicesLimitation
    and
    https://bugs.python.org/issue27227
    """
    repos = list(get_repos())
    repos.append([])
    return repos


def is_git(path: str) -> bool:
    """
    Return True if the path is a git repo.
    """
    # An alternative is to call `git rev-parse --is-inside-work-tree`
    # I don't see why that one is better yet.
    # For a regular git repo, .git is a folder, for a worktree repo, .git is a file.
    # However, git submodule repo also has .git as a file.
    # A more reliable way to differentiable regular and worktree repos is to
    # compare the result of `git rev-parse --git-dir` and
    # `git rev-parse --git-common-dir`
    loc = os.path.join(path, '.git')
    # TODO: we can display the worktree repos in a different font.
    return os.path.exists(loc)


def rename_repo(repos: Dict[str, str], repo: str, new_name: str):
    """
    Write new repo name to file
    """
    path = repos[repo]
    del repos[repo]
    repos[new_name] = path
    write_to_repo_file(repos, 'w')


def write_to_repo_file(repos: Dict[str, str], mode: str):
    """
    """
    data = ''.join(f'{path},{name}\n' for name, path in repos.items())
    fname = get_path_fname()
    os.makedirs(os.path.dirname(fname), exist_ok=True)
    with open(fname, mode) as f:
        f.write(data)


def add_repos(repos: Dict[str, str], new_paths: List[str]):
    """
    Write new repo paths to file
    """
    existing_paths = set(repos.values())
    new_paths = set(os.path.abspath(p) for p in new_paths if is_git(p))
    new_paths = new_paths - existing_paths
    if new_paths:
        print(f"Found {len(new_paths)} new repo(s).")
        new_repos = {
                os.path.basename(os.path.normpath(path)): path
                for path in new_paths}
        write_to_repo_file(new_repos, 'a+')
    else:
        print('No new repos found!')


async def run_async(path: str, cmds: List[str]) -> Union[None, str]:
    """
    Run `cmds` asynchronously in `path` directory. Return the `path` if
    execution fails.
    """
    process = await asyncio.create_subprocess_exec(
        *cmds,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        cwd=path)
    stdout, stderr = await process.communicate()
    stdout and print(stdout.decode())
    stderr and print(stderr.decode())
    # The existence of stderr is not good indicator since git sometimes write
    # to stderr even if the execution is successful, e.g. git fetch
    if process.returncode != 0:
        return path


def exec_async_tasks(tasks: List[Coroutine]) -> List[Union[None, str]]:
    """
    Execute tasks asynchronously
    """
    # TODO: asyncio API is nicer in python 3.7
    if platform.system() == 'Windows':
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.get_event_loop()

    try:
        errors = loop.run_until_complete(asyncio.gather(*tasks))
    finally:
        loop.close()
    return errors


def describe(repos: Dict[str, str]) -> str:
    """
    Return the status of all repos
    """
    if repos:
        name_width = max(len(n) for n in repos) + 1
    funcs = info.get_info_funcs()
    for name in sorted(repos):
        path = repos[name]
        display_items = ' '.join(f(path) for f in funcs)
        yield f'{name:<{name_width}}{display_items}'


def get_cmds_from_files() -> Dict[str, Dict[str, str]]:
    """
    Parse delegated git commands from default config file
    and custom config file.

    Example return
    {
      'branch': {'help': 'show local branches'},
      'clean': {'cmd': 'clean -dfx',
                'help': 'remove all untracked files/folders'},
    }
    """
    # default config file
    fname = os.path.join(os.path.dirname(__file__), "cmds.yml")
    with open(fname, 'r') as stream:
        cmds = yaml.load(stream, Loader=yaml.FullLoader)

    # custom config file
    root = os.environ.get('XDG_CONFIG_HOME') or os.path.join(
        os.path.expanduser('~'), '.config')
    fname = os.path.join(root, 'gita', 'cmds.yml')
    custom_cmds = {}
    if os.path.isfile(fname):
        with open(fname, 'r') as stream:
            custom_cmds = yaml.load(stream, Loader=yaml.FullLoader)

    # custom commands shadow default ones
    cmds.update(custom_cmds)
    return cmds
