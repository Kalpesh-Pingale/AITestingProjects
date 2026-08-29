# Requirements Clarification Report – SHOP‑1  

---  

## 1. Story  

| **Key** | **Summary** | **Original Story Text** |
|---------|------------|--------------------------|
| **SHOP‑1** | New‑user registration with email & password | *As a new user, I want to register with my email and password so that I can create an account and shop online.* |

---  

## 2. Verdict  

**Status:** **NEEDS CLARIFICATION**  

**Rationale:**  
The story contains the essential functional flow but leaves critical details unspecified (e.g., exact password complexity, exact wording and placement of error messages, email‑verification requirements, rate‑limiting limits, accessibility standards, and audit‑logging). Although the analysis proposes sensible defaults, they remain **assumptions** that must be confirmed with the Product Owner before work can be started. Without this confirmation the development effort cannot be reliably estimated and automated tests cannot be written with deterministic pass/fail criteria.  

**Risk Level:** **Medium** – the missing details are all implementable, but an incorrect assumption could cause re‑work, security‑ or compliance‑issues, and delays in the sprint.

---  

## 3. Findings Summary  

### INVEST Assessment  

| Criterion | Rating | Reason |
|-----------|--------|--------|
| **Independent** | PASS | Can be delivered without other backlog items. |
| **Negotiable** | PASS | High‑level scope allows discussion. |
| **Valuable** | PASS | Core e‑commerce capability. |
| **Estimable** | **WEAK** | Ambiguous wording around password rules, error messages, email content, rate‑limiting, accessibility, and logging. |
| **Small** | PASS | Fits within a sprint. |
| **Testable** | **WEAK** | Current ACs lack measurable details; many edge‑cases and error‑paths are missing. |

### Ambiguities (original)  

| Quoted Phrase | Why it is Ambiguous | Impact if Left As‑Is |
|---------------|---------------------|----------------------|
| “Password must meet complexity rules (min length, special char)” | No concrete values (e.g., min 8? which specials?) | Unclear test cases; inconsistent implementation. |
| “Duplicate email leads to an error message” | No text, UI location, HTTP status, field highlight defined. | UX inconsistency; verification difficulty. |
| “Successful registration sends a confirmation email” | No subject, body, delivery time, verification link defined. | Cannot assert email correctness; downstream flows break. |
| “User redirected to login page after registration” | No timing, URL, or success banner defined. | Divergent UI behaviour. |
| “Registration form includes name, email, password, confirm password” | No field type, required/optional, validation rules. | Invalid data may be accepted. |

### Missing Acceptance Criteria (original)  

| Missing Scenario | Why It Is Missing |
|------------------|-------------------|
| Invalid email format | No validation feedback defined. |
| Password‑confirm mismatch | No UI error defined. |
| Empty required fields | No required‑field handling. |
| Email verification flow | No rule on account activation. |
| Rate‑limiting / throttling | No protection against spam. |
| Successful registration audit logging | No compliance logging. |
| Accessibility compliance | No ARIA / WCAG requirements. |
| Localization / language support | Not addressed. |
| Privacy consent (GDPR) | No consent checkbox. |

### Undefined Error Handling (original)  

| Failure Path | What Is Silent / Undefined |
|--------------|----------------------------|
| Server‑side validation error | No UI feedback, no retry, no status code. |
| Email service outage | No fallback / notification. |
| Network timeout | No guidance on retry / loading indicator. |
| Concurrent duplicate registrations | No guarantee which request wins. |
| Unexpected exception (500) | No generic error page/message. |
| Password rule violation beyond min length / special char | No error description / UI handling. |

### Edge‑Case Gaps (original)  

| Edge‑Case Category | Specific Example(s) |
|--------------------|---------------------|
| Input length limits | Name >255 chars, email >254 chars, password exactly at min, password exceeding max. |
| Unicode / International characters | Names with diacritics, IDN emails, emojis in passwords. |
| Special email formats | `user+test@example.com`, quoted local part, sub‑domains. |
| Whitespace handling | Leading/trailing spaces, spaces inside passwords. |
| Case sensitivity | Email case variations, password case variations. |
| Concurrent submissions | Two requests with same email milliseconds apart. |
| SQL/Script injection attempts | `'; DROP TABLE users;--` |
| XSS | `<script>` payloads. |
| Browser compatibility | Mobile Safari vs. desktop Chrome. |
| Duplicate registration after email verification | Register again with already verified email. |

---  

## 4. Clarification Questions  

*(Unchanged – to be answered by the Product Owner)*  

1. **Q1:** When the password fails complexity rules, what exact minimum length and which special characters are required? → Suggested default: Minimum 8 characters, at least one of `! @ # $ % ^ & * ( )`.  
2. **Q2:** How should a duplicate‑email error be presented (text, UI location, HTTP status, field highlight)? Options: *inline below the email field with text “Email already in use”, HTTP 409, field highlighted* **or** *banner at top with generic error, HTTP 400*. → Suggested default: Inline message “Email already in use”, HTTP 409, email field highlighted in red.  
3. **Q3:** What must the confirmation email contain (subject line, body elements, delivery time) and does it need a verification link that activates the account? → Suggested default: Subject “Confirm your account”, body includes welcome text + verification link, sent within 5 minutes, account inactive until link clicked.  
4. **Q4:** After a successful registration, should the user be redirected immediately, after a toast, and to which URL? Options: *Immediate redirect to `/login`* **or** *show success toast then redirect after 3 s*. → Suggested default: Show success toast for 2 s, then redirect to `/login`.  
5. **Q5:** For each field in the registration form, specify the input type, whether it is required, and any validation rules (e.g., name max length, email format). → Suggested default:  
   - Name: text, required, max 255 chars.  
   - Email: type email, required, must match RFC 5322.  
   - Password & Confirm: password, required, min 8 chars, at least one special character from `! @ # $ % ^ & * ( )`.  

6. **Q6:** What feedback should be shown for an invalid email format (e.g., missing “@” or spaces)? → Suggested default: Inline error “Please enter a valid email address” below the field.  

7. **Q7:** How must a password‑confirm mismatch be reported to the user? → Suggested default: Inline error “Passwords do not match” under the confirm‑password field.  

8. **Q8:** How should empty required fields be handled on submit? → Suggested default: Prevent submission and display “This field is required” inline for each empty field.  

9. **Q9:** Must the user verify the email before being allowed to log in, or can they log in immediately after registration? → Suggested default: Account remains inactive until the verification link is clicked; login blocked with message “Please verify your email first”.  

10. **Q10:** Should there be rate‑limiting on registration attempts? If so, what limits and lock‑out message? Options: *5 attempts per IP per hour* **or** *no limit*. → Suggested default: 5 attempts per IP per hour, lock‑out message “Too many attempts, please try again later”.  

11. **Q11:** Is an audit log entry required for every successful registration? What should it contain? → Suggested default: Yes – log user ID, timestamp, and IP address.  

12. **Q12:** What accessibility standard must the form meet (e.g., WCAG level) and are ARIA labels required? → Suggested default: WCAG 2.1 AA compliance with appropriate ARIA labels for all inputs.  

13. **Q13:** Which languages must the UI, error messages, and confirmation email support? → Suggested default: English only (additional locales can be added later).  

14. **Q14:** Is a privacy‑consent checkbox (e.g., GDPR opt‑in) required on the registration form? → Suggested default: Yes – required checkbox with link to the privacy policy.  

15. **Q15:** If a server‑side validation error occurs (e.g., DB write fails), what UI feedback and HTTP status should be returned? → Suggested default: Show generic inline banner “Registration failed, please try again”, HTTP 500.  

16. **Q16:** When the email service is unavailable and the confirmation email cannot be sent, what should the user see and what retry mechanism is expected? → Suggested default: Show inline banner “We could not send the confirmation email, please try again later”, and automatically retry up to 3 times.  

17. **Q17:** How should a network timeout during form submission be handled (loading indicator, retry option)? → Suggested default: Display spinner, then show toast “Request timed out, please retry” with a “Retry” button.  

18. **Q18:** If two submissions with the same email arrive simultaneously, which request succeeds and how is the losing request reported? → Suggested default: First request creates the account; the second receives the duplicate‑email error as defined in Q2.  

19. **Q19:** What generic message and page should be shown for an unexpected 500 error? → Suggested default: Full‑screen error page with headline “Something went wrong” and button “Return to Home”.  

20. **Q20:** For password rule violations beyond length/special‑char (e.g., prohibited characters), what error text and placement are required? → Suggested default: Inline error “Password contains invalid characters” below the password field.  

21. **Q21:** What is the maximum allowed length for the **name** field? → Suggested default: 255 characters.  

22. **Q22:** What is the maximum allowed length for the **email** field? → Suggested default: 254 characters (per RFC 5321).  

23. **Q23:** Is there a maximum length for the **password** field? If so, what is it? → Suggested default: 128 characters.  

24. **Q24:** Should the system accept Unicode characters in names and emails (e.g., diacritics, IDN)? → Suggested default: Yes – accept Unicode and IDN, storing email in punycode.  

25. **Q25:** Are special email formats such as plus‑addressing (`user+tag@example.com`), quoted local parts, and sub‑domains permitted? → Suggested default: Yes – all RFC‑compliant formats are allowed.  

26. **Q26:** How should leading or trailing whitespace in any field be treated? → Suggested default: Automatically trim before validation.  

27. **Q27:** Are spaces allowed inside passwords? → Suggested default: Yes – spaces are treated as valid characters.  

28. **Q28:** Is email comparison case‑insensitive and should emails be stored in lower‑case? → Suggested default: Compare case‑insensitively and store lower‑case.  

29. **Q29:** How must the system protect against SQL/script injection attempts in the **name** field? → Suggested default: Use parameterised queries and reject any input that fails sanitisation, returning a generic validation error.  

30. **Q30:** How should potential XSS payloads in any input be handled? → Suggested default: Encode output on rendering; no script execution allowed.  

31. **Q31:** Must the registration form function correctly on both mobile Safari and desktop Chrome? → Suggested default: Yes – responsive design tested on those browsers.  

32. **Q32:** If a user attempts to register again with an email that is already verified, what message should be shown? → Suggested default: Inline