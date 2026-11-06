import os
import stat
import yaml
import importlib.resources as resources

from langbot.pkg.config import model as file_model

# data/config.yaml holds the JWT secret, database credentials, and provider
# API keys. Keep it readable by the service account only.
_CONFIG_FILE_MODE = 0o600


def _open_config_for_write(path: str):
    """Open *path* for truncating writes, creating it with 0600."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    return os.fdopen(os.open(path, flags, _CONFIG_FILE_MODE), 'w', encoding='utf-8')


def _restrict_config_permissions(path: str) -> None:
    """Best-effort chmod for existing installs that used the default umask."""
    try:
        current = stat.S_IMODE(os.stat(path).st_mode)
        if current != _CONFIG_FILE_MODE:
            os.chmod(path, _CONFIG_FILE_MODE)
    except OSError:
        # Read-only mounts and non-POSIX filesystems keep working; the file is
        # still protected by the directory permissions there.
        pass


class YAMLConfigFile(file_model.ConfigFile):
    """YAML config file"""

    def __init__(
        self,
        config_file_name: str,
        template_resource_name: str = None,
        template_data: dict = None,
    ) -> None:
        self.config_file_name = config_file_name
        self.template_resource_name = template_resource_name
        self.template_data = template_data

    def exists(self) -> bool:
        return os.path.exists(self.config_file_name)

    async def get_template_file_str(self) -> str:
        if self.template_resource_name is None:
            return None

        with (
            resources.files('langbot.templates').joinpath(self.template_resource_name).open('r', encoding='utf-8') as f
        ):
            return f.read()

    async def create(self):
        if await self.get_template_file_str() is not None:
            with _open_config_for_write(self.config_file_name) as f:
                f.write(await self.get_template_file_str())
        elif self.template_data is not None:
            with _open_config_for_write(self.config_file_name) as f:
                yaml.dump(self.template_data, f, indent=4, allow_unicode=True)
        else:
            raise ValueError('template_file_name or template_data must be provided')

    async def load(self, completion: bool = True) -> dict:
        if not self.exists():
            await self.create()
        _restrict_config_permissions(self.config_file_name)

        template_file_str = await self.get_template_file_str()

        if template_file_str is not None:
            self.template_data = yaml.load(template_file_str, Loader=yaml.FullLoader)

        with open(self.config_file_name, 'r', encoding='utf-8') as f:
            try:
                cfg = yaml.load(f, Loader=yaml.FullLoader)
            except yaml.YAMLError as e:
                raise Exception(f'Syntax error in config file {self.config_file_name}: {e}')

        if completion:
            for key in self.template_data:
                if key not in cfg:
                    cfg[key] = self.template_data[key]

        return cfg

    async def save(self, cfg: dict):
        with _open_config_for_write(self.config_file_name) as f:
            yaml.dump(cfg, f, indent=4, allow_unicode=True)
        _restrict_config_permissions(self.config_file_name)

    def save_sync(self, cfg: dict):
        with _open_config_for_write(self.config_file_name) as f:
            yaml.dump(cfg, f, indent=4, allow_unicode=True)
        _restrict_config_permissions(self.config_file_name)
