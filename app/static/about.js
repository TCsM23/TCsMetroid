// Sends the contact form with EmailJS. Only loaded when ABOUT_EMAILJS is filled in.
(function () {
  const form = document.getElementById("about-contact-form");
  if (!form || !window.emailjs) return;

  const button = document.getElementById("about-contact-submit");
  const status = document.getElementById("about-contact-status");

  window.emailjs.init({ publicKey: form.dataset.key });

  function say(text, kind) {
    status.textContent = text;
    status.dataset.kind = kind || "";
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    button.disabled = true;
    say("Sending…");

    window.emailjs.sendForm(form.dataset.service, form.dataset.template, form).then(
      () => {
        form.reset();
        button.disabled = false;
        say("Message sent. Thank you!", "ok");
      },
      () => {
        button.disabled = false;
        say("Could not send. Please use one of the direct channels instead.", "error");
      }
    );
  });
})();
