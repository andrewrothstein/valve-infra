Build the GitLab job  runner container and push it to the fd.o registry for faster feedback loops while developing job-related functionality. The alternative, editing files in the Mesa CI requires rebuilding all the containers on the dependency chain of the job, which includes building Mesa. This can take 10 minutes or so, typically, which is quite inconvenient a brain-cache-trashy while developing in the upstream CI

    docker buildx build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger containers/gitlab-trigger/ --push
