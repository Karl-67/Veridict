from app.backend.agents.admin import AgreementAdmin


def test_agreement_admin_states_exist():
    admin = AgreementAdmin()
    assert hasattr(admin, "check")
