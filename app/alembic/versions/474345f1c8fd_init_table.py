"""init table

Revision ID: 474345f1c8fd
Revises: 
Create Date: 2022-02-08 23:22:14.686113

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "474345f1c8fd"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "categorypris",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_categorypris_id"), "categorypris", ["id"], unique=False)
    op.create_table(
        "factorymaps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("map", sa.JSON(), nullable=False),
        sa.Column(
            "created_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_factorymaps_id"), "factorymaps", ["id"], unique=False)
    op.create_index(op.f("ix_factorymaps_name"), "factorymaps", ["name"], unique=True)
    op.create_table(
        "logvalues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("previous_value", sa.String(length=512), nullable=False),
        sa.Column("new_value", sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_logvalues_id"), "logvalues", ["id"], unique=False)
    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("project", sa.String(length=50), nullable=False),
        sa.Column("process", sa.Integer(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("device_name", sa.String(length=20), nullable=False),
        sa.Column("x_axis", sa.Float(), nullable=False),
        sa.Column("y_axis", sa.Float(), nullable=False),
        sa.Column("is_rescue", sa.Boolean(), nullable=True),
        sa.Column("workshop", sa.Integer(), nullable=True),
        sa.Column(
            "created_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workshop"], ["factorymaps.id"], name="fk_devices_factorymaps_id_workshop"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_devices_id"), "devices", ["id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=50), nullable=False),
        sa.Column("expertises", sa.JSON(), nullable=False),
        sa.Column("location", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default="0", nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["location"], ["factorymaps.id"], name="fk_users_factorymaps_id_location"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "auditlogheaders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("table_name", sa.String(length=50), nullable=False),
        sa.Column("record_pk", sa.String(length=100), nullable=True),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column(
            "created_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user"], ["users.id"], name="fk_auditlogheaders_users_id_user"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auditlogheaders_action"), "auditlogheaders", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_auditlogheaders_id"), "auditlogheaders", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_auditlogheaders_record_pk"),
        "auditlogheaders",
        ["record_pk"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auditlogheaders_table_name"),
        "auditlogheaders",
        ["table_name"],
        unique=False,
    )
    op.create_table(
        "categorypris_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("devices", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["category"],
            ["devices.id"],
            name="fk_categorypris_devices_devices_category_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["devices"],
            ["categorypris.id"],
            name="fk_categorypris_devices_categorypris_devices_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "devicemanageinfos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(length=100), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device"], ["devices.id"], name="fk_devicemanageinfos_devices_id_device"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "missions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=False),
        sa.Column("repair_start_date", sa.DateTime(), nullable=True),
        sa.Column("repair_end_date", sa.DateTime(), nullable=True),
        sa.Column("required_expertises", sa.JSON(), nullable=False),
        sa.Column("done_verified", sa.Boolean(), nullable=True),
        sa.Column("related_event_id", sa.Integer(), nullable=False),
        sa.Column("machine_status", sa.String(length=256), nullable=True),
        sa.Column("cause_of_issue", sa.String(length=512), nullable=True),
        sa.Column("issue_solution", sa.String(length=512), nullable=True),
        sa.Column("canceled_reason", sa.String(length=512), nullable=True),
        sa.Column("image", sa.LargeBinary(length=5242880), nullable=True),
        sa.Column("signature", sa.LargeBinary(length=5242880), nullable=True),
        sa.Column("is_cancel", sa.Boolean(), nullable=True),
        sa.Column(
            "created_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("event_start_date", sa.DateTime(), nullable=True),
        sa.Column("event_end_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device"], ["devices.id"], name="fk_missions_devices_id_device"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_missions_id"), "missions", ["id"], unique=False)
    op.create_table(
        "userdevicelevels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(length=100), nullable=True),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("shift", sa.Boolean(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["device"], ["devices.id"], name="fk_userdevicelevels_devices_id_device"
        ),
        sa.ForeignKeyConstraint(
            ["user"], ["users.id"], name="fk_userdevicelevels_users_id_user"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device", "user", name="uc_userdevicelevels_device_user"),
    )
    op.create_index(
        op.f("ix_userdevicelevels_id"), "userdevicelevels", ["id"], unique=False
    )
    op.create_table(
        "usershiftinfos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("attend", sa.Boolean(), nullable=True),
        sa.Column("day_or_night", sa.String(length=5), nullable=False),
        sa.ForeignKeyConstraint(
            ["user"], ["users.id"], name="fk_usershiftinfos_users_id_user"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user", "shift_date", name="uc_usershiftinfos_user_shift_date"
        ),
    )
    op.create_index(
        op.f("ix_usershiftinfos_id"), "usershiftinfos", ["id"], unique=False
    )
    op.create_table(
        "worker_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker", sa.String(length=36), nullable=True),
        sa.Column("at_device", sa.String(length=100), nullable=True),
        sa.Column("last_event_end_date", sa.DateTime(), nullable=True),
        sa.Column("dispatch_count", sa.Integer(), nullable=True),
        sa.Column(
            "updated_date",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["at_device"], ["devices.id"], name="fk_worker_status_devices_id_at_device"
        ),
        sa.ForeignKeyConstraint(
            ["worker"], ["users.id"], name="fk_worker_status_users_id_worker"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "auditlogheaders_logvalues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("logvalue", sa.Integer(), nullable=True),
        sa.Column("auditlogheader", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["auditlogheader"],
            ["auditlogheaders.id"],
            name="fk_auditlogheaders_logvalues_auditlogheaders_auditlogheader_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["logvalue"],
            ["logvalues.id"],
            name="fk_auditlogheaders_logvalues_logvalues_logvalue_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deviceinfo_chiefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("devicemanageinfo", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["devicemanageinfo"],
            ["devicemanageinfos.id"],
            name="fk_deviceinfo_chiefs_devicemanageinfos_devicemanageinfo_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user"],
            ["users.id"],
            name="fk_deviceinfo_chiefs_users_user_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deviceinfo_managers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("devicemanageinfo", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["devicemanageinfo"],
            ["devicemanageinfos.id"],
            name="fk_deviceinfo_managers_devicemanageinfos_devicemanageinfo_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user"],
            ["users.id"],
            name="fk_deviceinfo_managers_users_user_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deviceinfo_supervisors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("devicemanageinfo", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["devicemanageinfo"],
            ["devicemanageinfos.id"],
            name="fk_deviceinfo_supervisors_devicemanageinfos_devicemanageinfo_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user"],
            ["users.id"],
            name="fk_deviceinfo_supervisors_users_user_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "missions_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user", sa.String(length=36), nullable=True),
        sa.Column("mission", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mission"],
            ["missions.id"],
            name="fk_missions_users_missions_mission_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user"],
            ["users.id"],
            name="fk_missions_users_users_user_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "usershiftinfos_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(length=100), nullable=True),
        sa.Column("usershiftinfo", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device"],
            ["devices.id"],
            name="fk_usershiftinfos_devices_devices_device_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usershiftinfo"],
            ["usershiftinfos.id"],
            name="fk_usershiftinfos_devices_usershiftinfos_usershiftinfo_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("usershiftinfos_devices")
    op.drop_table("missions_users")
    op.drop_table("deviceinfo_supervisors")
    op.drop_table("deviceinfo_managers")
    op.drop_table("deviceinfo_chiefs")
    op.drop_table("auditlogheaders_logvalues")
    op.drop_table("worker_status")
    op.drop_index(op.f("ix_usershiftinfos_id"), table_name="usershiftinfos")
    op.drop_table("usershiftinfos")
    op.drop_index(op.f("ix_userdevicelevels_id"), table_name="userdevicelevels")
    op.drop_table("userdevicelevels")
    op.drop_index(op.f("ix_missions_id"), table_name="missions")
    op.drop_table("missions")
    op.drop_table("devicemanageinfos")
    op.drop_table("categorypris_devices")
    op.drop_index(op.f("ix_auditlogheaders_table_name"), table_name="auditlogheaders")
    op.drop_index(op.f("ix_auditlogheaders_record_pk"), table_name="auditlogheaders")
    op.drop_index(op.f("ix_auditlogheaders_id"), table_name="auditlogheaders")
    op.drop_index(op.f("ix_auditlogheaders_action"), table_name="auditlogheaders")
    op.drop_table("auditlogheaders")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_devices_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_index(op.f("ix_logvalues_id"), table_name="logvalues")
    op.drop_table("logvalues")
    op.drop_index(op.f("ix_factorymaps_name"), table_name="factorymaps")
    op.drop_index(op.f("ix_factorymaps_id"), table_name="factorymaps")
    op.drop_table("factorymaps")
    op.drop_index(op.f("ix_categorypris_id"), table_name="categorypris")
    op.drop_table("categorypris")
    # ### end Alembic commands ###
