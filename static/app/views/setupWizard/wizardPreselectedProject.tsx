import {useEffect} from 'react';

import LoadingIndicator from 'sentry/components/loadingIndicator';
import {t} from 'sentry/locale';
import type {OrganizationWithRegion} from 'sentry/views/setupWizard/types';
import {useUpdateWizardCache} from 'sentry/views/setupWizard/utils/useUpdateWizardCache';
import {WaitingForWizardToConnect} from 'sentry/views/setupWizard/waitingForWizardToConnect';
import {WizardProjectSelection} from 'sentry/views/setupWizard/wizardProjectSelection';

/**
 * Submits an org/project preselected via URL params through the CSRF-protected
 * POST endpoint. Falls back to the manual selection form if that fails.
 */
export function WizardPreselectedProject({
  hash,
  organizations,
  organizationId,
  projectId,
}: {
  hash: string;
  organizationId: string;
  organizations: OrganizationWithRegion[];
  projectId: string;
}) {
  const {mutate, isSuccess, isError, isIdle} = useUpdateWizardCache(hash);

  useEffect(() => {
    if (isIdle) {
      mutate({organizationId, projectId});
    }
  }, [isIdle, mutate, organizationId, projectId]);

  if (isSuccess) {
    return <WaitingForWizardToConnect hash={hash} organizations={organizations} />;
  }

  if (isError) {
    return <WizardProjectSelection hash={hash} organizations={organizations} />;
  }

  return (
    <LoadingIndicator style={{margin: '2em auto'}}>
      <h5>{t('Connecting your project')}</h5>
    </LoadingIndicator>
  );
}
