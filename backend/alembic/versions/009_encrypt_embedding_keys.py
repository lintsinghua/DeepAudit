"""Encrypt embedding keys saved by earlier releases."""
import json

import sqlalchemy as sa
from alembic import op

from app.core.encryption import decrypt_sensitive_data, encryption_service, protect_embedding_key

revision = "009_encrypt_embedding_keys"
down_revision = "008_add_files_with_findings"
branch_labels = None
depends_on = None


def _update_keys(transform):
    db = op.get_bind()
    configs = sa.table("user_configs", sa.column("id", sa.String), sa.column("other_config", sa.Text))
    query = sa.select(configs.c.id, configs.c.other_config).where(
        configs.c.other_config.contains('"embedding_config"')
    ).with_for_update()
    for config_id, raw in db.execute(query):
        settings = json.loads(raw)
        updated = transform(settings)
        if updated is not settings:
            db.execute(configs.update().where(configs.c.id == config_id).values(other_config=json.dumps(updated)))


def upgrade():
    _update_keys(protect_embedding_key)


def downgrade():
    # The previous release expects the original representation when reading user settings.
    def restore_key(settings):
        embedding = settings.get("embedding_config")
        key = embedding.get("api_key") if isinstance(embedding, dict) else None
        if key and encryption_service.is_encrypted(key):
            return {**settings, "embedding_config": {**embedding, "api_key": decrypt_sensitive_data(key)}}
        return settings

    _update_keys(restore_key)
