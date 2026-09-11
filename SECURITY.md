# Security Policy

## Supported Versions

Please always use the latest version of Astakos for security updates. 

| Version | Supported          |
| ------- | ------------------ |
| v2.7.x  | :white_check_mark: |
| < 2.7   | :x:                |

## Deployment Boundary

Astakos uses ChromaDB as an embedded local store. The supported Docker and
manual deployments do not expose a Chroma HTTP server. Do not publish a Chroma
server port or place one on an untrusted network; current upstream ChromaDB
server advisories affect its HTTP/API authorization boundary.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Use GitHub Private Vulnerability Reporting for this repository. Include reproduction steps, affected version, impact, and any suggested mitigation.
