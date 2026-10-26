## MODIFIED Requirements

### Requirement: App shell and sidebar navigation (F21)
The app SHALL be titled "ACME Corp IPA" and show a persistent left sidebar with the name, the tagline "Invoice Processing Automation", and menu items in this order: Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments. The active page SHALL be highlighted.

#### Scenario: Menu order and active page
- **WHEN** a user opens the Payment Queue page
- **THEN** the sidebar lists the six items in the order Home, Invoice Queue, Payment Queue, Invoice Elevated Review, Invoice Resolution Audit, Payments, and highlights Payment Queue

#### Scenario: Direct navigation by URL
- **WHEN** a user loads the Invoice Elevated Review page's URL directly
- **THEN** the shell renders with that page active and no other page content shown

#### Scenario: Collapsed sidebar keeps the order
- **WHEN** the window is narrower than 960 px and the sidebar shows icons only
- **THEN** the icons appear in the same order as the full menu
