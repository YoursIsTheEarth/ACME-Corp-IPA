import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarRef, TextOnlySnackBar } from '@angular/material/snack-bar';

/** Every toast in the app goes through here (Material snackbar, bottom center). */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly snackBar = inject(MatSnackBar);

  show(message: string, action?: string, durationMs = 5000): MatSnackBarRef<TextOnlySnackBar> {
    return this.snackBar.open(message, action ?? 'Dismiss', { duration: durationMs });
  }

  error(message: string): MatSnackBarRef<TextOnlySnackBar> {
    return this.snackBar.open(message, 'Dismiss', { duration: 8000, panelClass: 'toast-error' });
  }
}
