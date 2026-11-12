---
title: Project settings and members
description: Set a project's trace policy and manage who can use it.
---

Each project has a **Settings** page for what Polyweb records about its calls, and a **Members** page for who can use it. Both live in the project's sidebar. For what each role can do in general, see [Projects and roles](/concepts/projects-and-roles/).

## Change the trace policy

The Settings page has one section, **Trace policy**, with two fields.

| Field | Options | What it does |
| --- | --- | --- |
| **Payload detail** | **Metadata only**, **Full requests** | Metadata only stores timing, provider, outcome and counts. Full requests also stores the query or URL and the results. |
| **Retention** | **Delete old traces** switch, then a number of days (1 to 365) | With the switch off, traces stay until you delete them. With it on, old traces are deleted after that many days. |

API keys, auth headers, cookies, passwords and tokens are removed from traces in either mode.

1. Open your project, then open **Settings**.
2. Change a field. A bar at the bottom right counts your unsaved changes.
3. Select **Save changes**, or **Discard** to drop them.

A field can show **Set by system** when the system admin has fixed it, or "Overridden" with the system default and a **Reset** link when your project differs. Reset returns the field to the system default after you save. If the system limit is **Metadata only**, you can't choose **Full requests**.

If someone else saved first, you see "Settings changed since you opened them." Select **Reload settings** and make your change again.

You need the **Edit project settings** permission to change values. Without it you see the values and a note, "Ask a project admin to change this".

## Copy settings from another project

Select **Copy from another project** (it needs **Edit project settings** and **Copy settings**).

1. Choose a **Source project**.
2. Choose what to copy: **Changed values** (only what the other project changed from the system defaults) or **All current values** (everything; this project stops following the system defaults).
3. Select **Preview changes** and read the table. Settings that can't be copied are listed under **Not copied**.
4. If the source project has routes, tick any you want under **Also copy routes**.
5. Select **Apply changes**.

## See and add members

The **Members** page lists everyone in the project with their **Email**, **Role** and **Access**. Your own row is marked "(you)". A **Suspended** or **Account inactive** tag appears when that applies.

There are two roles. A **Project admin** has all permissions. A **Developer** has **Base access** (see the project, its members, settings and providers) plus the permissions you switch on. The **Access** column shows a summary such as "5 of 9 permissions".

To add someone, fill in the **New member** panel (you need `members.manage`).

1. Enter their **Account email**. The person must already have a Polyweb account.
2. Choose a **Role**: **Developer** or **Project admin**. A new developer starts with the Standard permission set.
3. Select **Add member**.

If the email is invalid or has no account, the error appears under the email field.

## Change a member's access

Open the **Actions** menu on a member's row. Which items you see depends on your permissions: `roles.assign` for role and permission changes, `members.manage` for the rest.

| Menu item | Effect |
| --- | --- |
| **Edit permissions** (**View permissions** for admins) | Opens a dialog with presets (**Read only**, **Standard**, **Full developer**) and one switch per permission. Select **Save permissions**. |
| **Make project admin** / **Make developer** | Changes the role. |
| **Suspend member** / **Reactivate member** | Removes or restores access without deleting the membership. You can't suspend yourself. |
| **Remove from project** | Removes the member after you confirm. |

The permissions you can switch on for a developer:

| Group | Permissions |
| --- | --- |
| Requests | **Run searches**, **Fetch pages** |
| Activity and usage | **View activity**, **View usage** |
| Configuration | **Edit project settings**, **Copy settings**, **Change provider order** |
| API keys | **Manage API keys** |

A project always keeps at least one active admin, so you can't demote, suspend or remove the last one ("A project needs one active admin.").

## Transfer provider ownership

One project admin is the provider owner, shown with a **Provider owner** tag. Changing the owner can stop providers until the new owner adds capacity.

The current provider owner opens the **Actions** menu and selects **Transfer provider ownership**, or **Make provider owner** on another admin's row. Choose the **New provider owner** from the active admins, read which providers will stop until that person adds capacity, and select **Transfer ownership**.

<!-- TODO(owner): explain what provider ownership means (whose provider keys back the project) and whether it belongs in concepts/projects-and-roles. -->

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Settings** or **Members** is missing from the sidebar | You lack the permission to read it. Ask a project admin. |
| The project page shows as not found | You aren't a member. Ask a system admin to add you. |
| Changes are refused on an archived project | Ask a project admin to unarchive it. |

## Next steps

- Set up what the project routes to in [Project providers](/dashboard/project-providers/).
- Read recorded calls in [Activity and traces](/dashboard/activity/).
