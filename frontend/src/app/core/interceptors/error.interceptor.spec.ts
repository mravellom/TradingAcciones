import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { errorInterceptor } from './error.interceptor';
import { NotificationService } from '../services/notification.service';

describe('errorInterceptor', () => {
  let httpMock: HttpTestingController;
  let http: HttpClient;
  let notification: NotificationService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    http = TestBed.inject(HttpClient);
    notification = TestBed.inject(NotificationService);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should pass through successful requests', () => {
    http.get('/test').subscribe((data) => {
      expect(data).toEqual({ ok: true });
    });
    httpMock.expectOne('/test').flush({ ok: true });
  });

  it('should show error toast on 500', () => {
    spyOn(notification, 'error');
    http.get('/test').subscribe({ error: () => {} });
    httpMock.expectOne('/test').flush('error', { status: 500, statusText: 'Server Error' });
    expect(notification.error).toHaveBeenCalledWith('Server error. Please try again later.');
  });

  it('should show auth required on 401', () => {
    spyOn(notification, 'error');
    http.get('/test').subscribe({ error: () => {} });
    httpMock.expectOne('/test').flush('', { status: 401, statusText: 'Unauthorized' });
    expect(notification.error).toHaveBeenCalledWith('Authentication required');
  });

  it('should show rate limit message on 429', () => {
    spyOn(notification, 'error');
    http.get('/test').subscribe({ error: () => {} });
    httpMock.expectOne('/test').flush('', { status: 429, statusText: 'Too Many Requests' });
    expect(notification.error).toHaveBeenCalledWith('Too many requests. Please wait and try again.');
  });

  it('should show not found on 404', () => {
    spyOn(notification, 'error');
    http.get('/test').subscribe({ error: () => {} });
    httpMock.expectOne('/test').flush('', { status: 404, statusText: 'Not Found' });
    expect(notification.error).toHaveBeenCalledWith('Resource not found');
  });
});
