import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NotificationService } from './notification.service';

describe('NotificationService', () => {
  let service: NotificationService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(NotificationService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should add a success toast', () => {
    service.success('Done!');
    service.toasts$.subscribe((toasts) => {
      expect(toasts.length).toBe(1);
      expect(toasts[0].type).toBe('success');
      expect(toasts[0].message).toBe('Done!');
    });
  });

  it('should add an error toast', () => {
    service.error('Failed!');
    service.toasts$.subscribe((toasts) => {
      expect(toasts.length).toBe(1);
      expect(toasts[0].type).toBe('error');
    });
  });

  it('should add a warning toast', () => {
    service.warning('Careful!');
    service.toasts$.subscribe((toasts) => {
      expect(toasts[0].type).toBe('warning');
    });
  });

  it('should add an info toast', () => {
    service.info('FYI');
    service.toasts$.subscribe((toasts) => {
      expect(toasts[0].type).toBe('info');
    });
  });

  it('should dismiss a toast by id', () => {
    service.success('First');
    service.error('Second');
    let toasts: any[] = [];
    service.toasts$.subscribe((t) => (toasts = t));

    expect(toasts.length).toBe(2);
    service.dismiss(toasts[0].id);
    expect(toasts.length).toBe(1);
    expect(toasts[0].message).toBe('Second');
  });

  it('should auto-dismiss after duration', fakeAsync(() => {
    service.success('Auto', 1000);
    let toasts: any[] = [];
    service.toasts$.subscribe((t) => (toasts = t));

    expect(toasts.length).toBe(1);
    tick(1000);
    expect(toasts.length).toBe(0);
  }));

  it('should assign unique ids', () => {
    service.success('A');
    service.success('B');
    let toasts: any[] = [];
    service.toasts$.subscribe((t) => (toasts = t));
    expect(toasts[0].id).not.toBe(toasts[1].id);
  });
});
