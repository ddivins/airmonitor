const form = document.getElementById("login-form");
const submit = document.getElementById("login-submit");
const errorBox = document.getElementById("login-error");

async function existingSession() {
  const response = await fetch("/session-api", {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) return false;
  return Boolean((await response.json()).authenticated);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  errorBox.hidden = true;
  try {
    const response = await fetch("/grafana/login", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        user: document.getElementById("login-user").value,
        password: document.getElementById("login-password").value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Sign in failed");
    window.location.replace("/");
  } catch (error) {
    errorBox.textContent = error.message || "Sign in failed";
    errorBox.hidden = false;
    submit.disabled = false;
  }
});

existingSession().then((authenticated) => {
  if (authenticated) window.location.replace("/");
}).catch(() => {});
