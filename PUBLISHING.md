# Releasing

How to cut a release and get it onto PyPI and the MCP Registry, so users can run it
with a single `uvx handelsregister-mcp`.

## 1. Bump the version

Keep these three in sync:

- `pyproject.toml` → `[project] version`
- `server.json` → `version` **and** `packages[0].version`
- `src/handelsregister_mcp/__init__.py` → `__version__`

## 2. Publish to PyPI

```bash
pip install build twine
python -m build                 # builds sdist + wheel into dist/
twine upload dist/*             # needs a PyPI token or Trusted Publisher
```

After this, `pip install handelsregister-mcp` and `uvx handelsregister-mcp` work for everyone.

> Tip: set up a **PyPI Trusted Publisher** (GitHub OIDC) so releases publish from CI with no
> stored token. See https://docs.pypi.org/trusted-publishers/

## 3. Publish to the MCP Registry

The registry indexes the PyPI package, so **publish to PyPI first**. Ownership of the
`io.github.lexdoudkin/*` namespace is proven via GitHub login; the README already carries the
required `<!-- mcp-name: io.github.lexdoudkin/handelsregister-mcp -->` marker.

```bash
# install the publisher CLI (see https://github.com/modelcontextprotocol/registry)
curl -sSL https://raw.githubusercontent.com/modelcontextprotocol/registry/main/install.sh | sh
mcp-publisher login github
mcp-publisher publish              # reads ./server.json
```

The server then appears at https://registry.modelcontextprotocol.io and in clients/directories
that mirror it.

## 4. Tag the release

```bash
git tag v0.1.0 && git push --tags
```

## Also worth listing on (manual, one-time)

- `modelcontextprotocol/servers` — PR a line to the community-servers list
- `awesome-mcp-servers` lists — PRs
- Directories: Glama, Smithery, PulseMCP, mcp.so
