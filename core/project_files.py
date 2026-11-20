"""Source snapshot rules, including engine scenes and their asset identity metadata."""
ENGINE_SUFFIXES = {
    '.gd', '.gdshader', '.gdextension', '.godot', '.tscn', '.tres', '.res', '.scn', '.uid', '.import',
    '.unity', '.prefab', '.asset', '.meta', '.mat', '.anim', '.controller', '.overridecontroller',
    '.shader', '.shadergraph', '.shadersubgraph', '.compute', '.cginc', '.hlsl', '.asmdef', '.asmref',
    '.csproj', '.sln', '.inputactions', '.uxml', '.uss',
    '.wav', '.ogg', '.mp3', '.flac', '.ttf', '.otf', '.woff', '.woff2',
    '.glb', '.gltf', '.fbx', '.blend', '.obj', '.mtl', '.tga', '.psd', '.exr',
}
ENGINE_ROOT_CACHES = {'library', 'temp', 'obj', 'logs', 'usersettings'}
CACHE_PARTS = {'.git', '.director_worktrees', '.venv', 'venv', 'node_modules', '__pycache__',
               '.godot', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
MAX_NEW_FILE_BYTES = 16 * 1024 * 1024
MAX_NEW_SNAPSHOT_BYTES = 128 * 1024 * 1024


def excluded_source_path(path):
    parts = [part.lower() for part in path.parts]
    if any(part in CACHE_PARTS for part in parts) or parts[0] in ENGINE_ROOT_CACHES:
        return True
    if any(part in {'secrets', 'credentials', '.credentials', '.secrets'} for part in parts[:-1]):
        return True
    name = parts[-1]
    config_suffix = path.suffix.lower() in {'.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.txt'}
    sensitive_config = config_suffix and (name.startswith(('secret_', 'secret-', 'credentials_', 'credentials-', 'api_key', 'api-key')) or name.endswith(('_token.json', '-token.json', '_tokens.json', '-tokens.json')))
    return (sensitive_config or name == '.env' or name.startswith('.env.') or name in {
        'credentials.json', 'credential.json', 'token.json', 'tokens.json', 'id_rsa', 'id_ed25519',
    } or name.endswith(('.key', '.pem', '.pfx', '.p12')) or 'private_key' in name)
