# SPDX-License-Identifier: Apache-2.0
# The frozen contract files a Famulus system needs at runtime: the default
# C5 policy (read by famulus-agentd and its PreToolUse hook) and the D-Bus
# interface definitions (C2, C4, C7). Built from a contracts-v* tag.
Name:           famulus-contracts
Version:        1
Release:        1%{?dist}
Summary:        Famulus interface contracts: default permission policy and D-Bus interfaces
License:        Apache-2.0
URL:            https://github.com/hoxton314/famulus-contracts
Source0:        %{url}/archive/contracts-v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3
BuildRequires:  python3-pyyaml
BuildRequires:  python3-jsonschema

%description
The definitions every Famulus component builds against, as installed
files: the default permission and tier policy (contract C5) that the
Famulus session daemon reads, and the D-Bus introspection files of the
Agent1, Conversation1, Snapshot1 and Audit1 interfaces (C2, C4, C7).

%prep
%autosetup

%build
# Nothing to build.

%install
install -Dm644 tier-policy/default-policy.yaml %{buildroot}%{_datadir}/famulus/tier-policy.yaml
for xml in dbus-agent/*.xml dbus-snapshot/*.xml dbus-audit/*.xml; do
    install -Dm644 "$xml" %{buildroot}%{_datadir}/dbus-1/interfaces/$(basename "$xml")
done

%check
# The shipped policy must pass the C5 validator (schema + contract floor).
python3 tier-policy/validate_policy.py %{buildroot}%{_datadir}/famulus/tier-policy.yaml

%files
%license LICENSE
%doc README.md
%dir %{_datadir}/famulus
%{_datadir}/famulus/tier-policy.yaml
%{_datadir}/dbus-1/interfaces/org.famulus.*.xml

%changelog
* Thu Oct 15 2026 Famulus maintainers <noreply@famulus.dev> - 1-1
- Package the contracts-v1 runtime files.
