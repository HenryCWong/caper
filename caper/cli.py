#!/usr/bin/env python3
import json
import logging
import os
import sys

from autouri import GCSURI, AutoURI

from . import __version__ as version
from .caper_args import get_parser_and_defaults
from .caper_client import CaperClient, CaperClientSubmit
from .caper_init import init_caper_conf
from .caper_labels import CaperLabels
from .caper_runner import CaperRunner
from .cromwell_backend import (
    BACKEND_ALIAS_LOCAL,
    BACKEND_LOCAL,
    CromwellBackendDatabase,
)
from .cromwell_metadata import CromwellMetadata
from .server_heartbeat import ServerHeartbeat

logger = logging.getLogger(__name__)


DEFAULT_TMP_DIR_NAME = '.caper_tmp'
DEFAULT_DB_FILE_PREFIX = 'caper_file_db'
DEFAULT_SERVER_HEARTBEAT_FILE = '~/.caper/default_server_heartbeat'
USER_INTERRUPT_WARNING = '\n********** DO NOT CTRL+C MULTIPLE TIMES **********\n'


def get_abspath(path):
    """Get abspath from a string.
    This function is mainly used to make a command line argument an abspath
    since AutoURI module only works with abspath and full URIs
    (e.g. /home/there, gs://here/there).
    For example, "caper run toy.wdl --docker ubuntu:latest".
    AutoURI cannot recognize toy.wdl on CWD as a file path.
    It should be converted to an abspath first.
    To do so, use this function for local file path strings only (e.g. toy.wdl).
    Do not use this function for other non-local-path strings (e.g. --docker).
    """
    if path:
        if not AutoURI(path).is_valid:
            return os.path.abspath(os.path.expanduser(path))
    return path


def print_version(parser, args):
    if args.version:
        print(version)
        parser.exit()


def init_logging(args):
    if args.debug:
        log_level = 'DEBUG'
    else:
        log_level = 'INFO'
    logging.basicConfig(
        level=log_level, format='%(asctime)s|%(name)s|%(levelname)s| %(message)s'
    )
    # suppress filelock logging
    logging.getLogger('filelock').setLevel('CRITICAL')


def init_autouri(args):
    if hasattr(args, 'use_gsutil_for_s3'):
        GCSURI.init_gcsuri(use_gsutil_for_s3=args.use_gsutil_for_s3)


def check_flags(args):
    singularity_flag = False
    docker_flag = False

    if hasattr(args, 'singularity') and args.singularity:
        singularity_flag = True
        if args.singularity.endswith(('.wdl', '.cwl')):
            raise ValueError(
                '--singularity ate up positional arguments (e.g. WDL, CWL). '
                'Define --singularity at the end of command line arguments. '
                'singularity={p}'.format(p=args.singularity)
            )

    if hasattr(args, 'docker') and args.docker:
        docker_flag = True
        if args.docker.endswith(('.wdl', '.cwl')):
            raise ValueError(
                '--docker ate up positional arguments (e.g. WDL, CWL). '
                'Define --docker at the end of command line arguments. '
                'docker={p}'.format(p=args.docker)
            )
        if hasattr(args, 'soft_glob_output') and args.soft_glob_output:
            raise ValueError(
                '--soft-glob-output and --docker are mutually exclusive. '
                'Delocalization from docker container will fail '
                'for soft-linked globbed outputs.'
            )

    if singularity_flag and docker_flag:
        raise ValueError('--docker and --singularity are mutually exclusive.')


def check_dirs(args):
    """Convert local directories (out_dir, tmp_dir) to absolute ones.
    Also, if temporar/cache directory is not defined for each storage,
    then append ".caper_tmp" on output directory and use it.
    """
    if hasattr(args, 'out_dir'):
        args.out_dir = get_abspath(args.out_dir)
        if not args.tmp_dir:
            args.tmp_dir = os.path.join(args.out_dir, DEFAULT_TMP_DIR_NAME)
    else:
        if not args.tmp_dir:
            args.tmp_dir = os.path.join(os.getcwd(), DEFAULT_TMP_DIR_NAME)

    args.tmp_dir = get_abspath(args.tmp_dir)

    if hasattr(args, 'out_gcs_bucket'):
        if args.out_gcs_bucket and not args.tmp_gcs_bucket:
            args.tmp_gcs_bucket = os.path.join(
                args.out_gcs_bucket, DEFAULT_TMP_DIR_NAME
            )

    if hasattr(args, 'out_s3_bucket'):
        if args.out_s3_bucket and not args.tmp_s3_bucket:
            args.tmp_s3_bucket = os.path.join(args.out_s3_bucket, DEFAULT_TMP_DIR_NAME)


def check_db_path(args):
    if hasattr(args, 'db') and args.db == CromwellBackendDatabase.DB_FILE:
        args.file_db = get_abspath(args.file_db)

        if not args.file_db:
            prefix = DEFAULT_DB_FILE_PREFIX
            if hasattr(args, 'inputs') and args.inputs:
                prefix += '_' + os.path.splitext(os.path.basename(args.inputs))[0]

            args.file_db = os.path.join(args.out_dir, prefix)


def check_backend(args):
    """Check if local backend is in lower cases.
    "Local" should be capitalized. i.e. local -> Local.
    BACKEND_LOCAL is Local.
    BACKEND_ALIAS_LOCAL is local.
    """
    if hasattr(args, 'backend') and args.backend == BACKEND_ALIAS_LOCAL:
        args.backend = BACKEND_LOCAL


def runner(args):
    c = CaperRunner(
        tmp_dir=args.tmp_dir,
        out_dir=args.out_dir,
        default_backend=args.backend,
        tmp_gcs_bucket=args.tmp_gcs_bucket,
        tmp_s3_bucket=args.tmp_s3_bucket,
        cromwell=get_abspath(args.cromwell),
        womtool=get_abspath(args.womtool),
        disable_call_caching=args.disable_call_caching,
        max_concurrent_workflows=args.max_concurrent_workflows,
        max_concurrent_tasks=args.max_concurrent_tasks,
        soft_glob_output=args.soft_glob_output,
        local_hash_strat=args.local_hash_strat,
        db=args.db,
        db_timeout=args.db_timeout,
        file_db=args.file_db,
        mysql_db_ip=args.mysql_db_ip,
        mysql_db_port=args.mysql_db_port,
        mysql_db_user=args.mysql_db_user,
        mysql_db_password=args.mysql_db_password,
        mysql_db_name=args.mysql_db_name,
        postgresql_db_ip=args.postgresql_db_ip,
        postgresql_db_port=args.postgresql_db_port,
        postgresql_db_user=args.postgresql_db_user,
        postgresql_db_password=args.postgresql_db_password,
        postgresql_db_name=args.postgresql_db_name,
        gcp_prj=args.gcp_prj,
        gcp_zones=args.gcp_zones,
        gcp_call_caching_dup_strat=args.gcp_call_caching_dup_strat,
        out_gcs_bucket=args.out_gcs_bucket,
        aws_batch_arn=args.aws_batch_arn,
        aws_region=args.aws_region,
        out_s3_bucket=args.out_s3_bucket,
        slurm_partition=getattr(args, 'slurm_partition', None),
        slurm_account=getattr(args, 'slurm_account', None),
        slurm_extra_param=getattr(args, 'slurm_extra_param', None),
        sge_pe=getattr(args, 'sge_pe', None),
        sge_queue=getattr(args, 'sge_queue', None),
        sge_extra_param=getattr(args, 'sge_extra_param', None),
        pbs_queue=getattr(args, 'pbs_queue', None),
        pbs_extra_param=getattr(args, 'pbs_extra_param', None),
    )

    if args.action == 'run':
        subcmd_run(c, args)

    elif args.action == 'server':
        subcmd_server(c, args)

    else:
        raise ValueError('Unsupported runner action {act}'.format(act=args.action))


def client(args):
    sh = None
    if not args.no_server_heartbeat:
        sh = ServerHeartbeat(
            heartbeat_file=args.server_heartbeat_file,
            heartbeat_timeout=args.server_heartbeat_timeout,
        )

    if args.action == 'submit':
        c = CaperClientSubmit(
            tmp_dir=args.tmp_dir,
            tmp_gcs_bucket=args.tmp_gcs_bucket,
            tmp_s3_bucket=args.tmp_s3_bucket,
            server_hostname=args.ip,
            server_port=args.port,
            server_heartbeat=sh,
            womtool=get_abspath(args.womtool),
            gcp_zones=args.gcp_zones,
            slurm_partition=args.slurm_partition,
            slurm_account=args.slurm_account,
            slurm_extra_param=args.slurm_extra_param,
            sge_pe=args.sge_pe,
            sge_queue=args.sge_queue,
            sge_extra_param=args.sge_extra_param,
            pbs_queue=args.pbs_queue,
            pbs_extra_param=args.pbs_extra_param,
        )
        subcmd_submit(c, args)

    else:
        c = CaperClient(
            tmp_dir=args.tmp_dir,
            tmp_gcs_bucket=args.tmp_gcs_bucket,
            tmp_s3_bucket=args.tmp_s3_bucket,
            server_hostname=args.ip,
            server_port=args.port,
            server_heartbeat=sh,
        )
        if args.action == 'abort':
            subcmd_abort(c, args)
        elif args.action == 'unhold':
            subcmd_unhold(c, args)
        elif args.action == 'list':
            subcmd_list(c, args)
        elif args.action == 'metadata':
            subcmd_metadata(c, args)
        elif args.action in ('troubleshoot', 'debug'):
            subcmd_troubleshoot(c, args)
        else:
            raise ValueError('Unsupported client action {act}'.format(act=args.action))


def subcmd_server(caper_runner, args):
    cromwell_stdout = get_abspath(args.cromwell_stdout)

    with open(cromwell_stdout, 'w') as f:
        sh = None
        if not args.no_server_heartbeat:
            sh = ServerHeartbeat(
                heartbeat_file=args.server_heartbeat_file,
                heartbeat_timeout=args.server_heartbeat_timeout,
            )
        try:
            th = caper_runner.server(
                default_backend=args.backend,
                server_port=args.port,
                server_heartbeat=sh,
                custom_backend_conf=get_abspath(args.backend_file),
                fileobj_stdout=f,
                embed_subworkflow=True,
                java_heap_server=args.java_heap_server,
                dry_run=args.dry_run,
            )
            th.join()
        except KeyboardInterrupt:
            logger.error(USER_INTERRUPT_WARNING)
            th.stop()


def subcmd_run(caper_runner, args):
    cromwell_stdout = get_abspath(args.cromwell_stdout)

    with open(cromwell_stdout, 'w') as f:
        try:
            th = caper_runner.run(
                backend=args.backend,
                wdl=get_abspath(args.wdl),
                inputs=get_abspath(args.inputs),
                options=get_abspath(args.options),
                labels=get_abspath(args.labels),
                imports=get_abspath(args.imports),
                metadata_output=get_abspath(args.metadata_output),
                str_label=args.str_label,
                docker=args.docker,
                singularity=args.singularity,
                singularity_cachedir=args.singularity_cachedir,
                no_build_singularity=args.no_build_singularity,
                custom_backend_conf=get_abspath(args.backend_file),
                max_retries=args.max_retries,
                ignore_womtool=args.ignore_womtool,
                no_deepcopy=args.no_deepcopy,
                fileobj_stdout=f,
                fileobj_troubleshoot=sys.stdout,
                java_heap_run=args.java_heap_run,
                java_heap_womtool=args.java_heap_womtool,
                dry_run=args.dry_run,
            )
            th.join()
        except KeyboardInterrupt:
            logger.error(USER_INTERRUPT_WARNING)
            th.stop()


def subcmd_submit(caper_client, args):
    caper_client.submit(
        wdl=get_abspath(args.wdl),
        backend=args.backend,
        inputs=get_abspath(args.inputs),
        options=get_abspath(args.options),
        labels=get_abspath(args.labels),
        imports=get_abspath(args.imports),
        str_label=args.str_label,
        docker=args.docker,
        singularity=args.singularity,
        singularity_cachedir=args.singularity_cachedir,
        no_build_singularity=args.no_build_singularity,
        max_retries=args.max_retries,
        ignore_womtool=args.ignore_womtool,
        no_deepcopy=args.no_deepcopy,
        hold=args.hold,
        java_heap_womtool=args.java_heap_womtool,
        dry_run=args.dry_run,
    )


def subcmd_abort(caper_client, args):
    caper_client.abort(args.wf_id_or_label)


def subcmd_unhold(caper_client, args):
    caper_client.unhold(args.wf_id_or_label)


def subcmd_list(caper_client, args):
    workflows = caper_client.list(args.wf_id_or_label)

    formats = args.format.split(',')
    print('\t'.join(formats))
    if workflows is None:
        return
    for w in workflows:
        row = []
        workflow_id = w['id'] if 'id' in w else None
        parent_workflow_id = w['parentWorkflowId'] if 'parentWorkflowId' in w else None

        if args.hide_subworkflow and parent_workflow_id:
            continue
        if args.hide_result_before is not None:
            if 'submission' in w and w['submission'] <= args.hide_result_before:
                continue
        for f in formats:
            if f == 'workflow_id':
                row.append(str(workflow_id))
            elif f == 'str_label':
                if 'labels' in w and CaperLabels.KEY_CAPER_STR_LABEL in w['labels']:
                    lbl = w['labels'][CaperLabels.KEY_CAPER_STR_LABEL]
                else:
                    lbl = None
                row.append(str(lbl))
            elif f == 'user':
                if 'labels' in w and CaperLabels.KEY_CAPER_USER in w['labels']:
                    lbl = w['labels'][CaperLabels.KEY_CAPER_USER]
                else:
                    lbl = None
                row.append(str(lbl))
            else:
                row.append(str(w[f] if f in w else None))
        print('\t'.join(row))


def subcmd_metadata(caper_client, args):
    m = caper_client.metadata(
        wf_ids_or_labels=args.wf_id_or_label, embed_subworkflow=True
    )
    if len(m) > 1:
        raise ValueError('Found multiple workflow matching with search query.')
    elif len(m) == 0:
        raise ValueError('Found no workflow matching with search query.')

    print(json.dumps(m[0], indent=4))


def subcmd_troubleshoot(caper_client, args):
    if len(args.wf_id_or_label) > 1:
        raise ValueError(
            'Multiple queries are not allowed for troubleshoot. '
            'Use workflow_id or metadata JSON file path.'
        )

    # check if it's a file
    u_metadata = AutoURI(get_abspath(args.wf_id_or_label[0]))

    if u_metadata.exists:
        metadata = json.loads(u_metadata.read())
    else:
        m = caper_client.metadata(
            wf_ids_or_labels=args.wf_id_or_label, embed_subworkflow=True
        )
        if len(m) > 1:
            raise ValueError('Found multiple workflow matching with search query.')
        elif len(m) == 0:
            raise ValueError('Found no workflow matching with search query.')
        metadata = m[0]

    # start troubleshooting
    cm = CromwellMetadata(metadata)
    cm.troubleshoot(
        fileobj=sys.stdout,
        show_completed_task=args.show_completed_task,
        show_stdout=args.show_stdout,
    )


def main(args=None):
    """
    Args:
        args:
            List of command line arguments.
            If defined use it instead of sys.argv.
    """
    parser, _ = get_parser_and_defaults()

    if args is None and len(sys.argv[1:]) == 0:
        parser.print_help()
        parser.exit()

    known_args, _ = parser.parse_known_args(args)
    check_flags(known_args)
    print_version(parser, known_args)

    parsed_args = parser.parse_args()

    init_logging(parsed_args)
    init_autouri(parsed_args)
    check_dirs(parsed_args)
    check_db_path(parsed_args)
    check_backend(parsed_args)

    if parsed_args.action == 'init':
        init_caper_conf(parsed_args.conf, parsed_args.platform)

    if parsed_args.action in ('run', 'server'):
        runner(parsed_args)
    else:
        client(parsed_args)


if __name__ == '__main__':
    main()
