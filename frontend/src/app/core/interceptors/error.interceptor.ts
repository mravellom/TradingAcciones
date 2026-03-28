import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from '../services/notification.service';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notification = inject(NotificationService);

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      let message = 'An unexpected error occurred';

      if (error.status === 0) {
        message = 'Unable to connect to server';
      } else if (error.status === 401) {
        message = 'Authentication required';
      } else if (error.status === 403) {
        message = 'Access denied';
      } else if (error.status === 404) {
        message = 'Resource not found';
      } else if (error.status === 429) {
        message = 'Too many requests. Please wait and try again.';
      } else if (error.status >= 500) {
        message = error.error?.message || 'Server error. Please try again later.';
      } else if (error.error?.message) {
        message = error.error.message;
      }

      notification.error(message);
      return throwError(() => error);
    })
  );
};
