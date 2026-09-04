import {Fragment} from 'react';

import Indicators from 'sentry/components/indicators';
import LoadingError from 'sentry/components/loadingError';
import LoadingIndicator from 'sentry/components/loadingIndicator';
import {t} from 'sentry/locale';
import {useSetupWizardViewedAnalytics} from 'sentry/views/setupWizard/utils/setupWizardAnalytics';
import {useOrganizationsWithRegion} from 'sentry/views/setupWizard/utils/useOrganizationsWithRegion';
import {WaitingForWizardToConnect} from 'sentry/views/setupWizard/waitingForWizardToConnect';
import {WizardPreselectedProject} from 'sentry/views/setupWizard/wizardPreselectedProject';
import {WizardProjectSelection} from 'sentry/views/setupWizard/wizardProjectSelection';

type Props = {
  hash: string;
  enableProjectSelection?: boolean;
  preselectedOrganizationId?: string | null;
  preselectedProjectId?: string | null;
};

function SetupWizard({
  hash,
  enableProjectSelection = false,
  preselectedOrganizationId = null,
  preselectedProjectId = null,
}: Props) {
  const {data: organizations, isError, isLoading} = useOrganizationsWithRegion();

  useSetupWizardViewedAnalytics(organizations);

  if (isLoading) {
    return <LoadingIndicator />;
  }

  if (isError || !organizations) {
    return <LoadingError message={t('Failed to load organizations')} />;
  }

  return (
    <Fragment>
      <Indicators />
      {enableProjectSelection && preselectedOrganizationId && preselectedProjectId ? (
        <WizardPreselectedProject
          hash={hash}
          organizations={organizations}
          organizationId={preselectedOrganizationId}
          projectId={preselectedProjectId}
        />
      ) : enableProjectSelection ? (
        <WizardProjectSelection hash={hash} organizations={organizations} />
      ) : (
        <WaitingForWizardToConnect hash={hash} organizations={organizations} />
      )}
    </Fragment>
  );
}

export default SetupWizard;
