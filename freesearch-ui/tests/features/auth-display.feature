Feature: Auth display errors and brand
  The login, register, and confirmation screens show friendly error text,
  the repository brand, and the configuration state. No screen shows a raw
  server body. Accounts carry no role, so neither signup nor administration
  offers an account-type choice and both send exactly {email, password}.

  @stub
  Scenario: Register shows the friendly password rule without raw JSON
    Given the auth bootstrap reports an anonymous session
    And the auth backend rejects registration with the password rule
    When I open the register screen
    And I submit a registration with a weak password
    Then the register screen shows the password rule text
    And the register screen shows no raw JSON body
    And the register screen offers no account-type choice
    And the registration request carried only email and password

  @stub
  Scenario: Login shows friendly bad-credentials text without raw JSON
    Given the auth bootstrap reports an anonymous session
    And the auth backend rejects login with bad credentials
    When I open the login screen
    And I submit a login with any credentials
    Then the login screen shows the bad-credentials text
    And the login screen shows no raw JSON body

  @stub
  Scenario: Auth screens show the repository brand once with one page title
    Given the auth bootstrap reports an anonymous session
    When I open the login screen
    Then the auth screen shows the FreeSearch brand
    And the auth screen shows exactly one page title
    When I open the register screen
    Then the auth screen shows the FreeSearch brand
    And the auth screen shows exactly one page title

  @stub
  Scenario: Login shows the friendly configuration state when the secret is missing
    Given the auth bootstrap reports an anonymous session
    And the auth backend reports an unconfigured secret on login
    When I open the login screen
    And I submit a login with any credentials
    Then the login screen shows the configuration state text

  @stub
  Scenario: Administration creates an account with only email and password
    Given the sidebar session belongs to a system administrator
    And the account provisioning backend accepts new accounts
    When I open the account administration screen
    Then the account administration screen offers no account-type choice
    When I create the account from the administration screen
    Then the account provisioning request carried only email and password
    And the administration receipt names the account without a role
