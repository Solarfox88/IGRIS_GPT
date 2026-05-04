"""Tests for igris.core.patch_proposal module."""

import json
import os
import shutil
import tempfile

import pytest

from igris.core.patch_proposal import (
    PatchProposal,
    PatchFileChange,
    create_patch_proposal,
    list_patch_proposals,
    load_patch_proposal,
    validate_patch_proposal,
    apply_patch_proposal,
    reject_patch_proposal,
    generate_unified_diff,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "README.md").write_text("# Project\n")
    return str(tmp_path)


class TestGenerateDiff:
    def test_diff_generated(self):
        diff = generate_unified_diff("hello\n", "hello\nworld\n", "test.txt")
        assert "+" in diff
        assert "test.txt" in diff

    def test_diff_empty_same(self):
        diff = generate_unified_diff("same\n", "same\n", "test.txt")
        assert diff == ""

    def test_diff_create(self):
        diff = generate_unified_diff("", "new content\n", "new.txt")
        assert "+new content" in diff


class TestCreateProposal:
    def test_create_valid_proposal(self, tmp_project):
        proposal = create_patch_proposal(
            title="Add docs",
            description="Adding safe.md",
            files=[{"path": "docs/safe.md", "action": "create", "after": "# Safe\n"}],
            project_root=tmp_project,
        )
        assert proposal.id
        assert proposal.title == "Add docs"
        assert proposal.status == "proposed"
        assert len(proposal.files) == 1
        assert proposal.files[0].action == "create"
        assert proposal.files[0].diff  # diff should be generated

    def test_create_modify_reads_before(self, tmp_project):
        proposal = create_patch_proposal(
            title="Modify readme",
            description="Update README",
            files=[{"path": "README.md", "action": "modify", "after": "# Updated\n"}],
            project_root=tmp_project,
        )
        assert proposal.files[0].before == "# Project\n"
        assert proposal.files[0].diff

    def test_proposal_persists(self, tmp_project):
        proposal = create_patch_proposal(
            title="Test persist",
            description="Check file",
            files=[{"path": "docs/x.md", "action": "create", "after": "x\n"}],
            project_root=tmp_project,
        )
        loaded = load_patch_proposal(proposal.id, project_root=tmp_project)
        assert loaded is not None
        assert loaded.title == "Test persist"

    def test_list_proposals(self, tmp_project):
        create_patch_proposal(
            title="P1", description="", files=[{"path": "a.md", "action": "create", "after": "a"}],
            project_root=tmp_project,
        )
        create_patch_proposal(
            title="P2", description="", files=[{"path": "b.md", "action": "create", "after": "b"}],
            project_root=tmp_project,
        )
        patches = list_patch_proposals(project_root=tmp_project)
        assert len(patches) >= 2
        titles = [p["title"] for p in patches]
        assert "P1" in titles
        assert "P2" in titles


class TestValidation:
    def test_validate_safe_proposal(self, tmp_project):
        proposal = create_patch_proposal(
            title="Safe patch",
            description="Create doc",
            files=[{"path": "docs/safe.md", "action": "create", "after": "# Safe doc\n"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is True
        assert result.risk == "low"
        assert proposal.status == "validated"

    def test_validate_blocks_path_traversal(self, tmp_project):
        proposal = create_patch_proposal(
            title="Traversal",
            description="Escape root",
            files=[{"path": "../../../etc/passwd", "action": "modify", "after": "hacked"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False
        assert any("traversal" in r.lower() or "escapes" in r.lower() for r in result.reasons)

    def test_validate_blocks_env(self, tmp_project):
        proposal = create_patch_proposal(
            title="Env file",
            description="Modify env",
            files=[{"path": ".env", "action": "modify", "after": "SECRET=abc"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False
        assert any(".env" in r.lower() or "sensitive" in r.lower() for r in result.reasons)

    def test_validate_blocks_secret_filename(self, tmp_project):
        proposal = create_patch_proposal(
            title="Secret file",
            description="API key file",
            files=[{"path": "api_key_config.json", "action": "create", "after": "{}"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False
        assert any("sensitive" in r.lower() or "key" in r.lower() for r in result.reasons)

    def test_validate_blocks_secret_content(self, tmp_project):
        proposal = create_patch_proposal(
            title="Has secrets",
            description="Content with API key",
            files=[{"path": "docs/config.md", "action": "create", "after": "API_KEY=sk-abc123def456ghi789jkl012mno345pqr"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False
        assert len(result.secret_findings) > 0

    def test_validate_blocks_delete(self, tmp_project):
        proposal = create_patch_proposal(
            title="Delete file",
            description="Remove file",
            files=[{"path": "docs/safe.md", "action": "delete"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False
        assert any("delete" in r.lower() for r in result.reasons)
        assert result.risk == "high"

    def test_validate_blocks_git_dir(self, tmp_project):
        proposal = create_patch_proposal(
            title="Git hack",
            description="Write to .git",
            files=[{"path": ".git/config", "action": "modify", "after": "bad"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False

    def test_validate_blocks_igris_dir(self, tmp_project):
        proposal = create_patch_proposal(
            title="Igris dir",
            description="Write to .igris",
            files=[{"path": ".igris/tasks/1.json", "action": "modify", "after": "{}"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False

    def test_validate_blocks_binary_extension(self, tmp_project):
        proposal = create_patch_proposal(
            title="Binary",
            description="Upload binary",
            files=[{"path": "app.exe", "action": "create", "after": "binary data"}],
            project_root=tmp_project,
        )
        result = validate_patch_proposal(proposal, project_root=tmp_project)
        assert result.valid is False


class TestApply:
    def test_apply_without_validate_fails(self, tmp_project):
        proposal = create_patch_proposal(
            title="Not validated",
            description="Unapproved",
            files=[{"path": "docs/new.md", "action": "create", "after": "# New\n"}],
            project_root=tmp_project,
        )
        result = apply_patch_proposal(proposal.id, project_root=tmp_project)
        assert result["success"] is False
        assert "not validated" in result["error"].lower() or "validation" in result["error"].lower()

    def test_apply_creates_file(self, tmp_project):
        proposal = create_patch_proposal(
            title="Create file",
            description="New doc",
            files=[{"path": "docs/created.md", "action": "create", "after": "# Created\n"}],
            project_root=tmp_project,
        )
        validate_patch_proposal(proposal, project_root=tmp_project)
        result = apply_patch_proposal(proposal.id, project_root=tmp_project)
        assert result["success"] is True
        created_path = os.path.join(tmp_project, "docs", "created.md")
        assert os.path.exists(created_path)
        assert open(created_path).read() == "# Created\n"

    def test_apply_modifies_file(self, tmp_project):
        proposal = create_patch_proposal(
            title="Modify readme",
            description="Update",
            files=[{"path": "README.md", "action": "modify", "after": "# Updated\n"}],
            project_root=tmp_project,
        )
        validate_patch_proposal(proposal, project_root=tmp_project)
        result = apply_patch_proposal(proposal.id, project_root=tmp_project)
        assert result["success"] is True
        assert open(os.path.join(tmp_project, "README.md")).read() == "# Updated\n"

    def test_apply_updates_status(self, tmp_project):
        proposal = create_patch_proposal(
            title="Status check",
            description="Check status",
            files=[{"path": "docs/s.md", "action": "create", "after": "s\n"}],
            project_root=tmp_project,
        )
        validate_patch_proposal(proposal, project_root=tmp_project)
        apply_patch_proposal(proposal.id, project_root=tmp_project)
        loaded = load_patch_proposal(proposal.id, project_root=tmp_project)
        assert loaded.status == "applied"

    def test_apply_already_applied_fails(self, tmp_project):
        proposal = create_patch_proposal(
            title="Double apply",
            description="Twice",
            files=[{"path": "docs/d.md", "action": "create", "after": "d\n"}],
            project_root=tmp_project,
        )
        validate_patch_proposal(proposal, project_root=tmp_project)
        apply_patch_proposal(proposal.id, project_root=tmp_project)
        result = apply_patch_proposal(proposal.id, project_root=tmp_project)
        assert result["success"] is False


class TestReject:
    def test_reject_proposal(self, tmp_project):
        proposal = create_patch_proposal(
            title="To reject",
            description="Will be rejected",
            files=[{"path": "docs/r.md", "action": "create", "after": "r\n"}],
            project_root=tmp_project,
        )
        result = reject_patch_proposal(proposal.id, reason="Not needed", project_root=tmp_project)
        assert result["success"] is True
        loaded = load_patch_proposal(proposal.id, project_root=tmp_project)
        assert loaded.status == "rejected"
        assert loaded.reject_reason == "Not needed"

    def test_reject_applied_fails(self, tmp_project):
        proposal = create_patch_proposal(
            title="Applied then reject",
            description="Should fail",
            files=[{"path": "docs/ar.md", "action": "create", "after": "ar\n"}],
            project_root=tmp_project,
        )
        validate_patch_proposal(proposal, project_root=tmp_project)
        apply_patch_proposal(proposal.id, project_root=tmp_project)
        result = reject_patch_proposal(proposal.id, project_root=tmp_project)
        assert result["success"] is False
