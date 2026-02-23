import resend

resend.api_key = "re_JJirzKQF_6sib63wUoXdAWSu6YpfGjmMx"

# Step 1: Verify the domain
print("=== Verifying domain ===")
try:
    result = resend.Domains.verify(domain_id="b9d5474f-2bc4-44ec-8871-cff4dfc77e37")
    print(f"Verify result: {result}")
except Exception as e:
    print(f"Verify error: {e}")

# Step 2: Check domain status
print("\n=== Checking domain status ===")
try:
    domain = resend.Domains.get(domain_id="b9d5474f-2bc4-44ec-8871-cff4dfc77e37")
    print(f"Domain info: {domain}")
except Exception as e:
    print(f"Get domain error: {e}")

# Step 3: Try sending email with verified domain
print("\n=== Sending test email ===")
try:
    r = resend.Emails.send({
        "from": "Jarvis <hi@furtadoben.com>",
        "to": ["raynfurtado@gmail.com"],
        "subject": "Hi from Jarvis",
        "html": "<p>Hi! This is a test email from Jarvis.</p>"
    })
    print(f"Send success: {r}")
except Exception as e:
    print(f"Send error: {e}")
