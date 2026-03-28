import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface Toast {
  id: number;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration: number;
}

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private _toasts$ = new BehaviorSubject<Toast[]>([]);
  toasts$ = this._toasts$.asObservable();
  private _nextId = 0;

  success(message: string, duration = 3000) { this._add('success', message, duration); }
  error(message: string, duration = 5000) { this._add('error', message, duration); }
  warning(message: string, duration = 4000) { this._add('warning', message, duration); }
  info(message: string, duration = 3000) { this._add('info', message, duration); }

  dismiss(id: number) {
    this._toasts$.next(this._toasts$.value.filter(t => t.id !== id));
  }

  private _add(type: Toast['type'], message: string, duration: number) {
    const id = this._nextId++;
    const toast: Toast = { id, type, message, duration };
    this._toasts$.next([...this._toasts$.value, toast]);
    if (duration > 0) {
      setTimeout(() => this.dismiss(id), duration);
    }
  }
}
