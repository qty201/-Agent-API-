"""Tests for analyzer agent — breaking change detection and version comparison."""

from agents.analyzer_agent import AnalyzerAgent, CompatibilityIssue
from parsers.python_parser import PythonParser
from parsers.js_ts_parser import JsTsParser


def test_version_comparison_gte():
    agent = None  # static method only
    assert AnalyzerAgent._version_gte("18.0.0", "18.0.0") is True
    assert AnalyzerAgent._version_gte("18.0.1", "18.0.0") is True
    assert AnalyzerAgent._version_gte("19.0.0", "18.0.0") is True
    assert AnalyzerAgent._version_gte("17.0.0", "18.0.0") is False
    assert AnalyzerAgent._version_gte("5.0.0", "5.0.0") is True
    assert AnalyzerAgent._version_gte("5.1", "5.0.0") is True


def test_issue_dataclass():
    issue = CompatibilityIssue(
        dependency="react",
        current_version="17.0.0",
        target_version="18.0.0",
        severity="break",
        description="ReactDOM.render removed",
    )
    d = issue.to_dict()
    assert d["dependency"] == "react"
    assert d["severity"] == "break"


def test_issue_from_dict():
    data = {
        "dependency": "express",
        "current_version": "3.0.0",
        "target_version": "4.0.0",
        "severity": "break",
        "description": "app.configure removed",
    }
    issue = CompatibilityIssue.from_dict(data)
    assert issue.dependency == "express"
    assert issue.severity == "break"


# ── parser tests ───────────────────────────────────────────────

def test_python_parser_simple_import():
    parser = PythonParser()
    source = __file__  # parse this file itself
    parsed = parser.parse(source)
    imports = [i for i in parsed.imports if i.module]
    assert len(imports) > 0
    # At minimum we should find the imports at the top of this file
    assert any("agents.analyzer_agent" in i.module for i in imports)


def test_python_parser_function_calls():
    parser = PythonParser()
    # Create a temporary Python file with known calls
    import tempfile
    import os

    code = """
import os
result = os.path.join("a", "b")
print("hello")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        parsed = parser.parse(f.name)
    os.unlink(f.name)

    call_names = {c.name for c in parsed.function_calls}
    assert "join" in call_names
    assert "print" in call_names


def test_js_parser_imports():
    parser = JsTsParser()
    import tempfile
    import os

    code = """
import React from 'react'
import { useState, useEffect } from 'react'
const express = require('express')
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(code)
        f.flush()
        parsed = parser.parse(f.name)
    os.unlink(f.name)

    modules = {i.module for i in parsed.imports}
    assert "react" in modules
    assert "express" in modules


def test_js_parser_calls():
    parser = JsTsParser()
    import tempfile
    import os

    code = """
const el = document.getElementById('root')
console.log('hello')
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(code)
        f.flush()
        parsed = parser.parse(f.name)
    os.unlink(f.name)

    call_names = {c.name for c in parsed.function_calls}
    assert "getElementById" in call_names
    assert "log" in call_names
