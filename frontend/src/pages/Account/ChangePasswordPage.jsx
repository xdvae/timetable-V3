import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";
import { Button } from "@/components/ui/button.jsx";
import { Input } from "@/components/ui/input.jsx";
import { Label } from "@/components/ui/label.jsx";
import { FieldError, MutationError } from "@/components/feedback/mutation.jsx";
import { useAuth } from "@/hooks/use-auth.js";
import { useMutation } from "@/hooks/use-mutation.js";
import { useToast } from "@/hooks/use-toast.js";
import { changePassword } from "@/services/api/auth.js";

function PasswordField({ id, label, help, value, onChange, fieldError, disabled, show, onToggleShow }) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="relative mt-1.5">
        <Input
          id={id}
          type={show ? "text" : "password"}
          required
          minLength={8}
          autoComplete={id === "current_password" ? "current-password" : "new-password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          aria-describedby={fieldError ? `${id}-error` : undefined}
          className="pr-10"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onToggleShow}
          disabled={disabled}
          aria-label={show ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={show}
          className="absolute top-1/2 right-1 h-7 w-7 -translate-y-1/2"
        >
          {show ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </Button>
      </div>
      {help ? <p className="mt-1 text-xs text-muted-foreground">{help}</p> : null}
      <FieldError id={`${id}-error`} message={fieldError} />
    </div>
  );
}

export function ChangePasswordPage() {
  const toast = useToast();
  const { user } = useAuth();
  const { execute, isSubmitting, error, fieldErrors } = useMutation(changePassword);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    const result = await execute({
      currentPassword,
      newPassword,
      confirmPassword,
    });
    if (result.ok) {
      toast.success(result.data.message || "Password changed.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } else if (result.error) {
      toast.error(result.error.message || "Could not change password.");
    }
  }

  return (
    <Page
      title="Change Password"
      subtitle={user ? `Signed in as ${user.username}.` : "Update your sign-in password."}
    >
      <div className="max-w-[420px]">
        <Panel accent="steel" title="Update password">
          <form onSubmit={handleSubmit} className="space-y-4">
            <MutationError error={error && !error.fieldErrors ? error : null} />
            <PasswordField
              id="current_password"
              label="Current password"
              value={currentPassword}
              onChange={setCurrentPassword}
              fieldError={fieldErrors.current_password}
              disabled={isSubmitting}
              show={showCurrent}
              onToggleShow={() => setShowCurrent((s) => !s)}
            />
            <PasswordField
              id="new_password"
              label="New password"
              help="At least 8 characters."
              value={newPassword}
              onChange={setNewPassword}
              fieldError={fieldErrors.new_password}
              disabled={isSubmitting}
              show={showNew}
              onToggleShow={() => setShowNew((s) => !s)}
            />
            <PasswordField
              id="confirm_password"
              label="Confirm new password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              fieldError={fieldErrors.confirm_password}
              disabled={isSubmitting}
              show={showConfirm}
              onToggleShow={() => setShowConfirm((s) => !s)}
            />
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Changing…" : "Change Password"}
            </Button>
          </form>
        </Panel>
      </div>
    </Page>
  );
}
